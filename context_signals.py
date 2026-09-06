"""Dated weather-model context for explicitly identified cities.

No epidemiological probability, severity adjustment, flight flow or calibrated
outbreak forecast is produced. Open-Meteo's past_days are model products, not
independent observations. Missing measurements remain null throughout.
"""

import copy
import json
import math
import re
import urllib.parse
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone


OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_DOCS = "https://open-meteo.com/en/docs"
EWARS_URL = "https://www.who.int/publications/i/item/9789240003750"
CACHE_HOURS = 6
MAX_SITES = 12
TIMEOUT_SECONDS = 8
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
VECTOR_DISEASES = {"dengue", "chikungunya", "zika", "yellow fever", "malaria", "west nile"}
RAINFALL_DISEASES = {"cholera", "leptospirosis", "typhoid", "hepatitis e"}
_EXCLUDED_BROAD_PLACES = {"Bali", "Goa", "Zanzibar"}
_EXTRA_CITY_NAMES = {"New York", "Los Angeles", "Chicago", "San Francisco", "Houston", "Dallas"}


def _as_datetime(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _number(value, *, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    if minimum is not None and value < minimum:
        return None
    if maximum is not None and value > maximum:
        return None
    return float(value)


def _city(location):
    """Require a named known city, not a plausible coordinate or a country pin."""
    if not isinstance(location, dict):
        return None
    from scanner_v2 import GEO_DB
    from signal_quality import _EXTRA_GEO
    cities = []
    for entry in GEO_DB:
        # The scanner's city section precedes its country fallback section.
        if entry["name"] == "Thailand":
            break
        if entry["name"] not in _EXCLUDED_BROAD_PLACES:
            cities.append(entry)
    cities.extend(entry for entry in _EXTRA_GEO if entry["name"] in _EXTRA_CITY_NAMES)
    lat = _number(location.get("lat"), minimum=-90, maximum=90)
    lng = _number(location.get("lng"), minimum=-180, maximum=180)
    if lat is None or lng is None:
        return None
    for entry in cities:
        if (location.get("name") == entry["name"] and location.get("iso") == entry["iso"]
                and abs(lat - entry["lat"]) <= 0.25 and abs(lng - entry["lng"]) <= 0.25):
            return {"name": entry["name"], "country": entry["country"], "iso": entry["iso"],
                    "lat": lat, "lng": lng, "precision": "city"}
    return None


def _profile(disease):
    if isinstance(disease, dict):
        disease = disease.get("name", "")
    disease = str(disease or "").lower()
    if disease in VECTOR_DISEASES:
        relevance = "vector_context"
        label = "Vector and weather context"
        description = ("Review temperature, humidity and rainfall alongside local case trends and vector surveillance. "
                       "These weather values do not establish transmission or a universal outbreak threshold.")
    elif disease in RAINFALL_DISEASES:
        relevance = "rainfall_context"
        label = "Rainfall and water context"
        description = ("Review rainfall alongside local flood reports, water quality and sanitation information. "
                       "Rainfall alone does not establish flooding, exposure or an outbreak.")
    else:
        relevance = "no_validated_weather_model"
        label = "No validated weather model connected"
        description = "This tool has no validated weather-to-outbreak model for this disease; weather does not change its severity."
    return {"relevance": relevance, "label": label, "description": description,
            "reference_url": EWARS_URL,
            "reference_label": "WHO EWARS operational guide for dengue",
            "reference_scope": "Dengue surveillance methodology reference; this implementation is not EWARS and is not WHO-validated."}


def _url(city):
    return OPEN_METEO_URL + "?" + urllib.parse.urlencode({
        "latitude": city["lat"], "longitude": city["lng"],
        "daily": "temperature_2m_mean,precipitation_sum",
        "hourly": "relative_humidity_2m", "past_days": 7, "forecast_days": 7,
        "timezone": "UTC", "temperature_unit": "celsius", "precipitation_unit": "mm",
    })


def _key(city):
    return f"{city['iso']}:{city['name']}:{city['lat']:.4f}:{city['lng']:.4f}"


def _rows(payload, today):
    if not isinstance(payload, dict) or payload.get("error"):
        raise ValueError("Weather provider returned an error or a non-object response")
    if payload.get("utc_offset_seconds", 0) != 0:
        raise ValueError("Weather response is not in UTC")
    daily = payload.get("daily")
    hourly = payload.get("hourly")
    if not isinstance(daily, dict) or not isinstance(daily.get("time"), list):
        raise ValueError("Weather response is missing daily timestamps")
    if not isinstance(hourly, dict) or not isinstance(hourly.get("time"), list):
        raise ValueError("Weather response is missing hourly timestamps")
    daily_units = payload.get("daily_units") or {}
    hourly_units = payload.get("hourly_units") or {}
    if daily_units.get("temperature_2m_mean") not in ("°C", "celsius"):
        raise ValueError("Unexpected temperature unit")
    if daily_units.get("precipitation_sum") != "mm":
        raise ValueError("Unexpected precipitation unit")
    if hourly_units.get("relative_humidity_2m") != "%":
        raise ValueError("Unexpected relative humidity unit")
    temps = daily.get("temperature_2m_mean") or []
    rain = daily.get("precipitation_sum") or []
    humidity = hourly.get("relative_humidity_2m") or []
    if not all(isinstance(values, list) for values in (temps, rain, humidity)):
        raise ValueError("Weather variables must be arrays")
    by_date = {}
    for index, raw_day in enumerate(daily["time"]):
        try:
            day = date.fromisoformat(str(raw_day))
        except ValueError:
            continue
        if day in by_date:
            raise ValueError("Duplicate daily timestamps in weather response")
        by_date[day] = {
            "temperature_mean_c": _number(temps[index], minimum=-100, maximum=80) if index < len(temps) else None,
            "precipitation_mm": _number(rain[index], minimum=0) if index < len(rain) else None,
        }
    humidity_by_day = defaultdict(dict)
    duplicate_hours = set()
    for index, raw_time in enumerate(hourly["time"]):
        timestamp = _as_datetime(raw_time)
        if timestamp is None or timestamp.minute != 0 or timestamp.second != 0:
            continue
        day = timestamp.date()
        hour = timestamp.hour
        if hour in humidity_by_day[day]:
            duplicate_hours.add(day)
        humidity_by_day[day][hour] = _number(humidity[index], minimum=0, maximum=100) if index < len(humidity) else None
    out = []
    for offset in range(-7, 7):
        day = today + timedelta(days=offset)
        values = by_date.get(day, {"temperature_mean_c": None, "precipitation_mm": None})
        hours = humidity_by_day.get(day, {})
        complete_hours = len(hours) == 24 and day not in duplicate_hours and all(v is not None for v in hours.values())
        out.append({"date": day.isoformat(), **values,
                    "relative_humidity_mean_pct": round(sum(hours.values()) / 24, 1) if complete_hours else None,
                    "humidity_hours_available": sum(value is not None for value in hours.values())})
    return out


def _period(rows, kind):
    fields = {"temperature_mean_c": "temperature_mean_c", "precipitation_total_mm": "precipitation_mm",
              "relative_humidity_mean_pct": "relative_humidity_mean_pct"}
    out = {"start": rows[0]["date"], "end": rows[-1]["date"], "days": rows,
           "timezone": "UTC", "data_kind": kind, "expected_days": 7, "coverage": {}}
    for output_field, row_field in fields.items():
        values = [row[row_field] for row in rows if row[row_field] is not None]
        out["coverage"][output_field] = {"available_days": len(values), "expected_days": 7}
        out[output_field] = (round(sum(values) if output_field == "precipitation_total_mm" else sum(values) / 7, 1)
                             if len(values) == 7 else None)
    return out


def _weather(payload, city, fetched_at, today, source_url, cached):
    rows = _rows(payload, today)
    periods = {"recent": _period(rows[:7], "archived_weather_model"),
               "forecast": _period(rows[7:], "weather_forecast")}
    complete = all(period[field] is not None for period in periods.values()
                   for field in ("temperature_mean_c", "precipitation_total_mm", "relative_humidity_mean_pct"))
    if not any(row[field] is not None for row in rows for field in
               ("temperature_mean_c", "precipitation_mm", "relative_humidity_mean_pct")):
        raise ValueError("Weather response has no data in the requested date windows")
    return {"status": "available" if complete else "partial", "source": "Open-Meteo",
            "source_url": source_url, "documentation_url": OPEN_METEO_DOCS,
            "generated_at": fetched_at, "timestamp_meaning": "retrieved_at; model initialization time is not supplied by this endpoint",
            "location": city, "model_grid_location": {"lat": _number(payload.get("latitude")), "lng": _number(payload.get("longitude"))},
            "data_kind": "weather_model", "periods": periods, "cached": cached,
            "note": "Recent values are archived model output, not station observations. Forecast covers today and the following six UTC days.",
            "error": None if complete else "Some weather values are missing; incomplete aggregates remain null."}


def _timing(signal, now):
    published = _as_datetime(signal.get("published"))
    if published is None:
        return "Current weather context; report publication time is unknown, so temporal linkage is not established."
    if published > now:
        return "Current weather context; the report date is in the future and needs review."
    if now - published > timedelta(days=7):
        return "Current weather context only. This report is over seven days old; these conditions do not describe or explain the past report."
    return "Current weather context for this city; temporal overlap alone does not establish causation or transmission."


def enrich_context(signals, cache=None, opener=None, now=None):
    """Return enriched copies and a JSON-serializable six-hour weather cache.

    ``opener`` follows urllib.request.urlopen(url, timeout=...) and is injectable
    for offline tests. At most twelve unique relevant cities are selected, with
    review candidates before contextual documents. UTC date changes refresh the
    cache so recent and forecast windows never silently shift or lose a day.
    Errors remain visible on each affected signal; stale cache is not served as
    current weather. No input severity, event status or triage value is changed.
    """
    now = _as_datetime(now) if now is not None else datetime.now(timezone.utc)
    if now is None:
        raise ValueError("now must be an ISO timestamp or datetime")
    open_url = opener or urllib.request.urlopen
    enriched = copy.deepcopy(list(signals))
    old_sites = cache.get("sites", {}) if isinstance(cache, dict) and cache.get("version") == 1 else {}
    sites = copy.deepcopy(old_sites) if isinstance(old_sites, dict) else {}
    sites = {key: item for key, item in sites.items()
             if isinstance(item, dict) and (stamp := _as_datetime(item.get("fetched_at"))) is not None
             and timedelta(0) <= now - stamp <= timedelta(days=2)}
    grouped = {}
    for signal in sorted(enriched, key=lambda item: item.get("triage") != "review"):
        profile = _profile(signal.get("disease"))
        city = _city(signal.get("location"))
        weather = {"status": "not_requested", "source": "Open-Meteo", "source_url": None,
                   "generated_at": None, "location": city, "periods": {"recent": None, "forecast": None},
                   "data_kind": "weather_model", "relevance": profile["relevance"],
                   "relevance_note": profile["description"], "report_timing_note": _timing(signal, now)}
        if city is None:
            weather.update(status="needs_locality", reason="A named city or local area is required. Country, state and island centroids are not representative local weather.")
        elif profile["relevance"] == "no_validated_weather_model":
            weather["reason"] = profile["description"]
        else:
            key = _key(city)
            if key not in grouped and len(grouped) >= MAX_SITES:
                weather.update(status="deferred", reason="The twelve-city context limit was reached for this scan.")
            else:
                grouped.setdefault(key, {"city": city, "signals": []})["signals"].append(signal)
        signal["context"] = {
            "weather": weather, "profile": profile,
            "mobility": {"status": "not_connected", "reason": "Current route and passenger-volume data are required; airport presence cannot estimate exportation risk"},
            "forecast": {"status": "not_estimated",
                         "reason": "Weather and open-source reports alone cannot estimate outbreak probability, growth or severity. No locally validated epidemiological forecast is connected.",
                         "required_inputs": ["Local case and hospitalization time series with reporting delays",
                                             "Population, testing and surveillance denominators",
                                             "Disease-specific vector or environmental surveillance where relevant",
                                             "Current origin-destination passenger volumes and travel dates",
                                             "Locally fitted models, independent validation and uncertainty estimates"]},
        }
    rate_limited = False
    for key, group in grouped.items():
        city = group["city"]
        source_url = _url(city)
        entry = sites.get(key)
        stamp = _as_datetime(entry.get("fetched_at")) if isinstance(entry, dict) else None
        cached = bool(stamp and timedelta(0) <= now - stamp < timedelta(hours=CACHE_HOURS) and stamp.date() == now.date())
        try:
            if cached:
                payload = entry.get("payload")
                fetched_at = entry["fetched_at"]
            else:
                if rate_limited:
                    raise RuntimeError("Weather provider rate limit reached in this scan")
                request = urllib.request.Request(source_url, headers={
                    "User-Agent": "GeoSentinel/3.0 (+https://github.com/acuestamd/project-geosentinel)",
                    "Accept": "application/json"})
                with open_url(request, timeout=TIMEOUT_SECONDS) as response:
                    raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise ValueError("Weather response exceeds the size limit")
                payload = json.loads(raw)
                fetched_at = now.isoformat()
            weather = _weather(payload, city, fetched_at, now.date(), source_url, cached)
            sites[key] = {"fetched_at": fetched_at, "payload": payload}
        except Exception as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
                rate_limited = True
            weather = {"status": "unavailable", "source_url": source_url, "generated_at": None,
                       "error": f"{type(exc).__name__}: {exc}"[:240],
                       "last_successful_fetch": entry.get("fetched_at") if isinstance(entry, dict) else None,
                       "reason": "Weather retrieval or validation failed; no weather values are inferred."}
        for signal in group["signals"]:
            signal["context"]["weather"].update(copy.deepcopy(weather))
    sites = dict(sorted(sites.items(), key=lambda item: item[1]["fetched_at"], reverse=True)[:256])
    return enriched, {"version": 1, "sites": sites}
