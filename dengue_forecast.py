#!/usr/bin/env python3
"""Experimental, revision-limited Rio dengue forecasts; standard library only.

The target is InfoDengue ``casos`` (reported cases), never its nowcast or alert.
Historical evaluation uses today's revised series, NOT historical data vintages.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MODEL_VERSION = "rio-reported-v1"
GEOCODE = "3304557"
API_BASE = "https://info.dengue.mat.br/api/alertcity"
SOURCE_DOC = "https://info.dengue.mat.br/services/api"
MAX_BYTES = 4 * 1024 * 1024
CACHE_HOURS = 24
INTERVAL_LEVEL = 0.8
MIN_TRAIN = 156
MODELS = ("persistence", "seasonal", "ridge_cases", "ridge_weather")
LABELS = {"persistence": "Last reported week", "seasonal": "Same week, previous year (52 weeks)",
          "ridge_cases": "Cases + seasonality", "ridge_weather": "Cases + seasonality + weather"}
LIMITATIONS = [
    "Experimental city-specific forecast of reported dengue cases; not a severity forecast or a clinical recommendation.",
    "Historical evaluation uses the latest retrospectively revised notifications and weather. It is not an as-of backtest and may overstate real-time performance.",
    "Recent reported counts are provisional and can be much lower than eventual totals. The upstream nowcast is shown for context but is not a target or model input.",
    "Intervals are empirical 80% calibration bands, not guaranteed probabilities; they do not account for all reporting revisions or epidemic regime changes.",
    "No Google Trends, social media, flight data, hospital admissions, deaths, or healthcare capacity enter this model. No validated probability of an epidemic or serious disease is produced.",
    "Results require prospective evaluation with archived issue-time snapshots before operational use; no WHO validation is claimed.",
]


def utc_now():
    return datetime.now(timezone.utc)


def iso_time(value):
    return value.astimezone(timezone.utc).isoformat()


def api_url(year):
    return (f"{API_BASE}?geocode={GEOCODE}&disease=dengue&format=json"
            f"&ew_start=1&ew_end=53&ey_start=2015&ey_end={year}")


def finite_number(value, minimum=None, maximum=None):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(number) or (minimum is not None and number < minimum) or (maximum is not None and number > maximum):
        return None
    return number


def week_date(value):
    if isinstance(value, bool):
        raise ValueError("Invalid epidemiological week")
    if isinstance(value, (int, float)):
        result = datetime.fromtimestamp(value / 1000, timezone.utc).date()
    elif isinstance(value, str):
        result = date.fromisoformat(value[:10])
    else:
        raise ValueError("Missing epidemiological week")
    if result.weekday() != 6:
        raise ValueError("Epidemiological weeks must start on Sunday")
    return result


def normalize_history(raw, now=None):
    """Reject ambiguous municipal totals, null counts, duplicates, and future rows.

    Missing meteorology remains null; a missing weekly row is never filled with 0.
    """
    now = now or utc_now()
    if not isinstance(raw, list) or not raw or len(raw) > 2000:
        raise ValueError("Expected a bounded, non-empty weekly series")
    rows, seen = [], set()
    for item in raw:
        if not isinstance(item, dict) or str(item.get("Localidade_id")) != "0":
            raise ValueError("Expected municipal aggregate Localidade_id=0")
        if item.get("municipio_nome") not in (None, "Rio de Janeiro"):
            raise ValueError("Unexpected municipality")
        week = week_date(item.get("data_iniSE"))
        if week < date(2015, 1, 1) or week > now.date():
            raise ValueError("Out-of-range epidemiological week")
        if week in seen:
            raise ValueError("Duplicate municipal epidemiological week")
        cases = finite_number(item.get("casos"), 0, 10_000_000)
        if cases is None or not cases.is_integer():
            raise ValueError("Missing or invalid reported case count")
        seen.add(week)
        rows.append({"week": week.isoformat(), "cases": int(cases),
                     "temperature_min": finite_number(item.get("tempmin"), -30, 60),
                     "humidity_max": finite_number(item.get("umidmax"), 0, 100),
                     "nowcast_cases": finite_number(item.get("casos_est"), 0, 10_000_000)})
    return sorted(rows, key=lambda row: row["week"])


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = handle.name
        json.dump(payload, handle, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        handle.write("\n")
    os.replace(temporary, path)


def load_data(cache_path, now=None, opener=urlopen):
    """Cache successes for 24 hours; retry a failed refresh at the next scan."""
    now = now or utc_now()
    cache = None
    try:
        path = Path(cache_path)
        if path.stat().st_size <= MAX_BYTES:
            loaded = json.loads(path.read_text())
            retrieved = datetime.fromisoformat(loaded["retrieved_at"])
            if retrieved.tzinfo is None:
                raise ValueError("Missing cache timezone")
            age = (now - retrieved).total_seconds()
            normalize_history(loaded["raw"], now)
            if loaded.get("geocode") != GEOCODE or age < 0:
                raise ValueError("Unexpected cache identity or timestamp")
            cache = loaded
            if age < CACHE_HOURS * 3600:
                return cache, "cached", None
    except (OSError, KeyError, ValueError, TypeError, OverflowError):
        pass
    try:
        request = Request(api_url(now.year), headers={"User-Agent": "GeoSentinel/3.1 (+https://github.com/acuestamd/project-geosentinel)", "Accept": "application/json"})
        with opener(request, timeout=25) as response:
            body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError("InfoDengue response exceeds size limit")
        raw = json.loads(body)
        normalize_history(raw, now)
        cache = {"schema_version": 1, "geocode": GEOCODE, "retrieved_at": iso_time(now), "raw": raw,
                 "raw_sha256": hashlib.sha256(body).hexdigest()}
        atomic_json(cache_path, cache)
        return cache, "fresh", None
    except (OSError, ValueError, TypeError, OverflowError, HTTPError, URLError) as exc:
        # Only a generic error class is published; response bodies and credentials are not.
        return cache, "stale" if cache else "unavailable", type(exc).__name__


def features(rows, index, weather=False):
    """Only observations at/before index; calendar terms describe origin, not future weather."""
    if index < 52:
        return None
    counts = [math.log1p(rows[index - lag]["cases"]) for lag in (0, 1, 2, 3, 4, 52)]
    origin = date.fromisoformat(rows[index]["week"])
    phase = 2 * math.pi * origin.timetuple().tm_yday / 365.2425
    result = [1.0] + counts + [math.sin(phase), math.cos(phase)]
    if weather:
        current = rows[index]
        recent = rows[index - 3:index + 1]
        if any(row[field] is None for row in recent for field in ("temperature_min", "humidity_max")):
            return None
        result += [current["temperature_min"] / 40, current["humidity_max"] / 100,
                   statistics.mean(row["temperature_min"] for row in recent) / 40,
                   statistics.mean(row["humidity_max"] for row in recent) / 100]
    return result


class Ridge:
    """Incremental sufficient statistics; fixed L2=1, unpenalized intercept."""
    def __init__(self, dimensions):
        self.matrix = [[0.0] * dimensions for _ in range(dimensions)]
        self.vector = [0.0] * dimensions
        self.count = 0

    def add(self, x, target):
        if x is None:
            return
        self.count += 1
        for i, value in enumerate(x):
            self.vector[i] += value * math.log1p(target)
            for j in range(len(x)):
                self.matrix[i][j] += value * x[j]

    def predict(self, x):
        if x is None or self.count < MIN_TRAIN:
            return None
        n = len(x)
        augmented = [row[:] + [target] for row, target in zip(self.matrix, self.vector)]
        for i in range(1, n):
            augmented[i][i] += 1.0
        for i in range(n):
            pivot = max(range(i, n), key=lambda j: abs(augmented[j][i]))
            augmented[i], augmented[pivot] = augmented[pivot], augmented[i]
            denominator = augmented[i][i]
            if abs(denominator) < 1e-12:
                return None
            augmented[i] = [v / denominator for v in augmented[i]]
            for j in range(n):
                if j != i:
                    multiplier = augmented[j][i]
                    augmented[j] = [v - multiplier * w for v, w in zip(augmented[j], augmented[i])]
        log_prediction = sum(x[i] * augmented[i][-1] for i in range(n))
        return max(0.0, math.expm1(min(math.log1p(10_000_000), log_prediction)))


def rolling_predictions(rows, data_lag_weeks=0):
    """Direct horizons; training labels are observed by each available-data cutoff.

    A target must be <= available_index before it can enter fitting. We keep all
    test origins independent of selection and calibration while permitting earlier
    observed test labels in a later rolling fit (normal online updating).
    """
    case_features = [features(rows, i) for i in range(len(rows))]
    weather_features = [features(rows, i, True) for i in range(len(rows))]
    records, live = [], []
    for horizon in range(1, 5):
        distance = horizon + data_lag_weeks
        case_model, weather_model = Ridge(9), Ridge(13)
        for available in range(52, len(rows)):
            training_origin = available - distance
            if training_origin >= 52:
                case_model.add(case_features[training_origin], rows[available]["cases"])
                weather_model.add(weather_features[training_origin], rows[available]["cases"])
            target = available + distance
            predictions = {
                "persistence": float(rows[available]["cases"]),
                "seasonal": float(rows[target - 52]["cases"]) if 0 <= target - 52 <= available else None,
                "ridge_cases": case_model.predict(case_features[available]),
                "ridge_weather": weather_model.predict(weather_features[available]),
            }
            target_week = date.fromisoformat(rows[available]["week"]) + timedelta(weeks=distance)
            record = {"horizon_weeks": horizon, "data_horizon_weeks": distance,
                      "available_week": rows[available]["week"], "week": target_week.isoformat(),
                      "predictions": predictions, "training_target_cutoff": rows[available]["week"]}
            if target < len(rows):
                record["actual"] = rows[target]["cases"]
                records.append(record)
            if available == len(rows) - 1:
                live.append(record)
    return records, live


def period(records, start, end):
    return [r for r in records if start <= r["week"] <= end]


def comparable(records):
    return [r for r in records if all(r["predictions"][name] is not None for name in MODELS)]


def mae(records, model):
    errors = [abs(r["actual"] - r["predictions"][model]) for r in records if r["predictions"][model] is not None]
    return statistics.mean(errors) if errors else None


def empirical_quantile(values, level=INTERVAL_LEVEL):
    if not values:
        raise ValueError("No calibration residuals")
    ordered = sorted(values)
    rank = min(len(ordered), math.ceil((len(ordered) + 1) * level))
    return ordered[rank - 1]


def bounds(point, width):
    log_point = math.log1p(point)
    return max(0.0, math.expm1(log_point - width)), math.expm1(min(math.log1p(10_000_000), log_point + width))


def evaluate(rows, data_lag_weeks=0):
    records, live = rolling_predictions(rows, data_lag_weeks)
    # Boundaries and selection rule were fixed before examining held-out results.
    development = comparable(period(records, "2019-01-01", "2021-12-31"))
    # Embargo origins before each boundary: otherwise a January target's December
    # cutoff would be evaluated using a choice/calibration that was still future.
    calibration = [r for r in period(records, "2022-01-01", "2023-12-31")
                   if r["available_week"] >= "2022-01-01"]
    # Exclude the latest four reported weeks from scored outcomes; this does not
    # resolve the older-vintage limitation, which remains explicit everywhere.
    test_end = (date.fromisoformat(rows[-1]["week"]) - timedelta(weeks=4)).isoformat()
    heldout = comparable([r for r in period(records, "2024-01-01", test_end)
                          if r["available_week"] >= "2024-01-01"])
    if len(development) < 200 or len(heldout) < 100:
        raise ValueError("Insufficient development or untouched test coverage")
    development_scores = {name: mae(development, name) for name in MODELS}
    baseline = min(("persistence", "seasonal"), key=lambda name: development_scores[name])
    candidate = min(("ridge_cases", "ridge_weather"), key=lambda name: development_scores[name])
    selected = candidate if development_scores[candidate] < development_scores[baseline] * 0.95 else baseline
    candidates = [{"model": name, "label": LABELS[name], "development_mae": round(development_scores[name], 2),
                   "development_n": len(development), "heldout_mae": round(mae(heldout, name), 2),
                   "heldout_n": len(heldout)} for name in MODELS]
    widths = {}
    for model in MODELS:
        for horizon in range(1, 5):
            group = [r for r in calibration if r["horizon_weeks"] == horizon and r["predictions"][model] is not None]
            if len(group) < 52:
                raise ValueError("Insufficient interval calibration coverage")
            widths[(model, horizon)] = empirical_quantile([
                abs(math.log1p(r["actual"]) - math.log1p(r["predictions"][model])) for r in group])
    horizons = []
    for horizon in range(1, 5):
        group = [r for r in heldout if r["horizon_weeks"] == horizon]
        baseline_error = mae(group, baseline)
        selected_error = mae(group, selected)
        covered = sum(bounds(r["predictions"][selected], widths[(selected, horizon)])[0] <= r["actual"] <=
                      bounds(r["predictions"][selected], widths[(selected, horizon)])[1] for r in group)
        horizons.append({"horizon_weeks": horizon, "data_horizon_weeks": horizon + data_lag_weeks,
                         "n": len(group), "baseline_mae": round(baseline_error, 2),
                         "case_model_mae": round(mae(group, "ridge_cases"), 2),
                         "weather_model_mae": round(mae(group, "ridge_weather"), 2),
                         "selected_model": selected, "selected_mae": round(selected_error, 2),
                         "skill_vs_baseline": round(1 - selected_error / baseline_error, 4) if baseline_error else None,
                         "interval_coverage": round(covered / len(group), 4)})
    result = {"design": "Rolling hindcast on latest revised data; no historical as-of vintages",
              "method": "Fixed chronological selection, separate interval calibration and untouched test",
              "train_period": {"start": rows[0]["week"], "end": "2018-12-31"},
              "development_period": {"start": "2019-01-01", "end": "2021-12-31"},
              "calibration_period": {"start": "2022-01-01", "end": "2023-12-31"},
              "test_period": {"start": "2024-01-01", "end": test_end},
              "selection_rule": "Choose the best development baseline; promote a ridge candidate only if development MAE improves by more than 5%. Test results never choose the model.",
              "selected_model": selected, "baseline": baseline, "candidates": candidates,
              "heldout": {"n": len(heldout), "mae": round(mae(heldout, selected), 2),
                          "baseline_mae": round(mae(heldout, baseline), 2)},
              "horizons": horizons, "origins": len({r["available_week"] for r in heldout}),
              "interval_method": "Horizon-specific 80% empirical absolute log-error bands from 2022–2023 only",
              "recent_outcomes_excluded_weeks": 4, "data_lag_weeks": data_lag_weeks}
    result["boundary_embargo"] = "Calibration data cutoffs start in 2022; test data cutoffs start in 2024. Targets remain inside their respective periods."
    return result, live, widths


def build_payload(cache, retrieval_status, error=None, now=None):
    now = now or utc_now()
    payload = {"schema_version": 1, "model_version": MODEL_VERSION, "status": "unavailable",
               "generated_at": iso_time(now), "issued_at": iso_time(now),
               "location": {"name": "Rio de Janeiro", "country": "Brazil", "geocode": GEOCODE},
               "source": {"name": "InfoDengue", "url": api_url(now.year), "documentation_url": SOURCE_DOC,
                          "retrieved_at": cache.get("retrieved_at") if cache else None,
                          "raw_sha256": cache.get("raw_sha256") if cache else None, "status": retrieval_status},
               "history": [], "forecasts": [], "evaluation": None, "model": None,
               "interval": {"level": INTERVAL_LEVEL, "method": "Empirical calibration; no guaranteed probability coverage"},
               "data_quality": {"valid_for_forecast": False, "notes": []}, "limitations": LIMITATIONS[:]}
    if error:
        payload["data_quality"]["notes"].append(f"Source refresh failed ({error}); no current forecast is issued.")
    if not cache:
        return payload
    try:
        rows = normalize_history(cache["raw"], now)
    except (ValueError, TypeError, KeyError, OverflowError):
        payload["data_quality"]["notes"].append("Historical series failed validation.")
        return payload
    current_week = now.date() - timedelta(days=(now.weekday() + 1) % 7)
    latest_complete_week = current_week - timedelta(weeks=1)
    # Incomplete calendar-week rows, if supplied upstream, never train this model.
    complete = [row for row in rows if row["week"] <= latest_complete_week.isoformat()]
    payload["history"] = rows
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    payload["source"]["data_sha256"] = hashlib.sha256(canonical).hexdigest()
    if not complete:
        payload["data_quality"]["notes"].append("No complete epidemiological week available.")
        return payload
    last = complete[-1]
    latest = date.fromisoformat(last["week"])
    gaps = [{"after": a["week"], "before": b["week"]} for a, b in zip(complete, complete[1:])
            if (date.fromisoformat(b["week"]) - date.fromisoformat(a["week"])).days != 7]
    age = (now.date() - latest).days
    lag = (latest_complete_week - latest).days // 7
    quality = payload["data_quality"]
    quality.update({"latest_week": last["week"], "latest_complete_week": latest_complete_week.isoformat(),
                    "age_days": age, "lag_days": max(0, (now.date() - (latest + timedelta(days=6))).days),
                    "data_lag_weeks": lag, "observations": len(complete), "gaps": gaps,
                    "latest_reported_cases": last["cases"], "latest_nowcast_cases": last["nowcast_cases"],
                    "reporting_delay_note": "Provisional notifications are revised retrospectively. InfoDengue nowcast is a separate estimate, not the predictor's input or observed truth.",
                    "weather_missing_weeks": sum(row["temperature_min"] is None or row["humidity_max"] is None for row in complete)})
    payload["origin_week"] = current_week.isoformat()
    payload["data_origin_week"] = last["week"]
    if retrieval_status == "stale" or lag > 2:
        payload["status"] = "stale"
        quality["notes"].append("Forecast paused: source refresh failed or latest completed data is more than two weeks behind the calendar origin.")
        return payload
    if gaps or len(complete) < 470:
        quality["notes"].append("Forecast paused: continuous historical coverage is insufficient; missing weeks are not converted to zero.")
        return payload
    try:
        # The current calendar week is already underway. Forecast the four next
        # complete weeks, all starting strictly after the issue date.
        evaluation, live, widths = evaluate(complete, lag + 1)
    except ValueError as exc:
        quality["notes"].append(str(exc))
        return payload
    selected = evaluation["selected_model"]
    active_model = selected
    if any(record["predictions"][selected] is None for record in live):
        active_model = evaluation["baseline"]
        quality["notes"].append("Selected model lacks current inputs; a development-selected baseline is used instead.")
    for record in live:
        point = record["predictions"][active_model]
        lower, upper = bounds(point, widths[(active_model, record["horizon_weeks"])])
        payload["forecasts"].append({"horizon_weeks": record["horizon_weeks"],
                                     "data_horizon_weeks": record["data_horizon_weeks"], "week": record["week"],
                                     "point": round(point, 1), "lower": round(lower, 1), "upper": round(upper, 1),
                                     "model": active_model})
    payload["model"] = {"name": active_model, "label": LABELS[active_model], "uses_weather": active_model == "ridge_weather"}
    payload["evaluation"] = evaluation
    payload["status"] = "ready"
    quality["valid_for_forecast"] = True
    quality["notes"].append("Forecast weeks start after the current calendar week. Source delay and the already-started current week are included in fitting and evaluation.")
    return payload


def unavailable_payload(now=None, error="Source unavailable"):
    return build_payload(None, "unavailable", error=error, now=now)


def validate_payload(payload):
    """Validate the public boundary before an artifact replaces the live pilot."""
    try:
        _validate_payload(payload)
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError("Malformed dengue payload") from exc


def _validate_payload(payload):
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("Invalid dengue schema")
    if payload.get("model_version") != MODEL_VERSION or payload.get("status") not in {"ready", "stale", "unavailable"}:
        raise ValueError("Invalid dengue model or status")
    try:
        issued = datetime.fromisoformat(payload["issued_at"])
        generated = datetime.fromisoformat(payload["generated_at"])
        if issued.tzinfo is None or generated.tzinfo is None:
            raise ValueError("Missing issue timezone")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid dengue issue date") from exc
    if not isinstance(payload.get("location"), dict) or payload["location"].get("geocode") != GEOCODE:
        raise ValueError("Invalid dengue location")
    if not isinstance(payload.get("source"), dict) or not payload["source"].get("url", "").startswith(API_BASE + "?"):
        raise ValueError("Invalid dengue source")
    history = payload.get("history")
    forecasts = payload.get("forecasts")
    quality = payload.get("data_quality")
    if not isinstance(history, list) or not isinstance(forecasts, list) or not isinstance(quality, dict):
        raise ValueError("Invalid dengue series")
    previous = None
    for row in history:
        if not isinstance(row, dict):
            raise ValueError("Invalid historical row")
        week = week_date(row.get("week"))
        if previous and week <= previous:
            raise ValueError("History must be sorted and unique")
        previous = week
        cases = finite_number(row.get("cases"), 0, 10_000_000)
        if cases is None or not cases.is_integer() or week > issued.date():
            raise ValueError("Invalid historical count or date")
        for field, minimum, maximum in (("temperature_min", -30, 60), ("humidity_max", 0, 100)):
            if row.get(field) is not None and finite_number(row[field], minimum, maximum) is None:
                raise ValueError("Invalid historical weather")
    if payload["status"] != "ready":
        if forecasts or quality.get("valid_for_forecast"):
            raise ValueError("Unavailable or stale payload cannot issue forecasts")
        return
    if quality.get("valid_for_forecast") is not True or quality.get("gaps") != [] or len(forecasts) != 4 or len(history) < 470:
        raise ValueError("Ready forecast requires continuous, sufficient data")
    complete = [row for row in history if row["week"] <= quality.get("latest_complete_week", "")]
    if any((week_date(b["week"]) - week_date(a["week"])).days != 7 for a, b in zip(complete, complete[1:])):
        raise ValueError("Ready history contains gaps")
    source = payload["source"]
    if source.get("status") not in {"fresh", "cached"}:
        raise ValueError("Ready forecast requires a successful source retrieval")
    retrieved = datetime.fromisoformat(source.get("retrieved_at", ""))
    if retrieved.tzinfo is None or not 0 <= (issued - retrieved).total_seconds() < CACHE_HOURS * 3600:
        raise ValueError("Ready forecast requires a fresh source cache")
    for field in ("data_sha256", "raw_sha256"):
        digest = source.get(field)
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("Ready forecast requires source fingerprints")
    canonical = json.dumps(history, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if hashlib.sha256(canonical).hexdigest() != source["data_sha256"]:
        raise ValueError("Published history differs from its source fingerprint")
    origin, data_origin = week_date(payload.get("origin_week")), week_date(payload.get("data_origin_week"))
    if not complete or complete[-1]["week"] != data_origin.isoformat():
        raise ValueError("Data origin differs from last complete observation")
    if origin > issued.date() or (issued.date() - origin).days >= 7:
        raise ValueError("Forecast origin must be current epidemiological week")
    expected_complete = origin - timedelta(weeks=1)
    actual_lag = (expected_complete - data_origin).days // 7
    if quality.get("latest_complete_week") != expected_complete.isoformat() or not 0 <= actual_lag <= 2:
        raise ValueError("Ready forecast has a stale or inconsistent data origin")
    if (quality.get("latest_week") != data_origin.isoformat() or quality.get("data_lag_weeks") != actual_lag or
            quality.get("observations") != len(complete) or quality.get("age_days") != (issued.date() - data_origin).days or
            quality.get("lag_days") != max(0, (issued.date() - (data_origin + timedelta(days=6))).days) or
            quality.get("latest_reported_cases") != complete[-1]["cases"]):
        raise ValueError("Ready data-quality metadata differs from its history")
    model = payload.get("model")
    if not isinstance(model, dict) or model.get("name") not in MODELS:
        raise ValueError("Invalid active forecast model")
    for horizon, forecast in enumerate(forecasts, start=1):
        if not isinstance(forecast, dict) or forecast.get("horizon_weeks") != horizon:
            raise ValueError("Invalid forecast horizon")
        week = week_date(forecast.get("week"))
        distance = (week - data_origin).days // 7
        if week <= issued.date() or week != origin + timedelta(weeks=horizon) or forecast.get("data_horizon_weeks") != distance:
            raise ValueError("Forecast must cover the next four future weeks")
        values = [finite_number(forecast.get(key), 0, 10_000_000) for key in ("lower", "point", "upper")]
        if any(value is None for value in values) or not values[0] <= values[1] <= values[2] or forecast.get("model") != model["name"]:
            raise ValueError("Invalid forecast interval or model")
    evaluation = payload.get("evaluation")
    if not isinstance(evaluation, dict) or evaluation.get("selected_model") not in MODELS or evaluation.get("baseline") not in MODELS[:2]:
        raise ValueError("Missing valid model evaluation")
    candidates = evaluation.get("candidates", [])
    if not isinstance(candidates, list) or {item.get("model") for item in candidates if isinstance(item, dict)} != set(MODELS):
        raise ValueError("Missing candidate comparison")
    for item in candidates:
        for key in ("development_mae", "heldout_mae", "development_n", "heldout_n"):
            if finite_number(item.get(key), 0) is None:
                raise ValueError("Invalid candidate metric")
    if not isinstance(evaluation.get("horizons"), list) or len(evaluation["horizons"]) != 4:
        raise ValueError("Missing horizon evaluation")
    for horizon, item in enumerate(evaluation["horizons"], start=1):
        if item.get("horizon_weeks") != horizon or finite_number(item.get("interval_coverage"), 0, 1) is None or finite_number(item.get("n"), 1) is None:
            raise ValueError("Invalid horizon evaluation")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="dengue_forecast.json")
    parser.add_argument("--cache", default="dengue_history_cache.json")
    args = parser.parse_args()
    now = utc_now()
    cache, status, error = load_data(args.cache, now)
    payload = build_payload(cache, status, error, now)
    validate_payload(payload)
    atomic_json(args.output, payload)
    print(f"Dengue pilot: {payload['status']}; {len(payload['history'])} observations; {len(payload['forecasts'])} forecasts")


if __name__ == "__main__":
    main()
