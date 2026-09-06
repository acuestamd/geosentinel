"""Temporal, data-integrity and publication tests for the experimental pilot."""
import copy
import hashlib
import io
import json
import math
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

import dengue_forecast as dengue


NOW = datetime(2026, 9, 6, 5, tzinfo=timezone.utc)


def raw_series(length=608):
    rows = []
    start = date(2015, 1, 4)
    for i in range(length):
        week = start + timedelta(weeks=i)
        rows.append({"data_iniSE": int(datetime.combine(week, datetime.min.time(), timezone.utc).timestamp() * 1000),
                     "Localidade_id": 0, "municipio_nome": "Rio de Janeiro",
                     "casos": round(100 + 40 * math.sin(2 * math.pi * i / 52) + i / 10),
                     "casos_est": 99999, "tempmin": 23 + math.sin(i / 8), "umidmax": 80})
    return rows


def cached(raw=None, retrieved=NOW):
    raw = raw if raw is not None else raw_series()
    return {"schema_version": 1, "geocode": dengue.GEOCODE, "retrieved_at": dengue.iso_time(retrieved),
            "raw": raw, "raw_sha256": hashlib.sha256(json.dumps(raw).encode()).hexdigest()}


class HistoricalDataTests(unittest.TestCase):
    def test_null_cases_and_submunicipal_rows_rejected(self):
        for field, value in (("casos", None), ("casos", -1), ("casos", True), ("casos", 1.5), ("Localidade_id", 2)):
            rows = raw_series(3)
            rows[0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                dengue.normalize_history(rows, NOW)

    def test_duplicate_and_wrong_municipality_rejected(self):
        rows = raw_series(3)
        with self.assertRaises(ValueError):
            dengue.normalize_history(rows + rows[:1], NOW)
        rows[0]["municipio_nome"] = "Another city"
        with self.assertRaises(ValueError):
            dengue.normalize_history(rows, NOW)

    def test_missing_weather_is_null_and_disables_weather_features(self):
        raw = raw_series(100)
        raw[-1]["tempmin"] = None
        raw[-1]["umidmax"] = "NaN"
        rows = dengue.normalize_history(raw, NOW)
        self.assertIsNone(rows[-1]["temperature_min"])
        self.assertIsNone(rows[-1]["humidity_max"])
        self.assertIsNone(dengue.features(rows, 99, True))
        self.assertIsNotNone(dengue.features(rows, 99, False))

    def test_missing_week_is_not_fabricated_zero(self):
        raw = raw_series()
        del raw[200]
        payload = dengue.build_payload(cached(raw), "fresh", now=NOW)
        self.assertEqual(len(payload["history"]), 607)
        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(len(payload["data_quality"]["gaps"]), 1)
        self.assertEqual(payload["forecasts"], [])

    def test_incomplete_current_week_does_not_enter_model(self):
        raw = raw_series(609)  # ends Aug 30; add current Sep 6 separately
        current = copy.deepcopy(raw[-1])
        current["data_iniSE"] += 7 * 86400 * 1000
        raw.append(current)
        payload = dengue.build_payload(cached(raw), "fresh", now=NOW)
        self.assertEqual(payload["data_origin_week"], "2026-08-30")
        self.assertEqual(payload["data_quality"]["observations"], 609)


class CacheTests(unittest.TestCase):
    def test_fresh_cache_avoids_network(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            dengue.atomic_json(path, cached())
            def forbidden(*args, **kwargs):
                raise AssertionError("Network must not be called")
            result, status, error = dengue.load_data(path, NOW + timedelta(hours=23), forbidden)
            self.assertEqual(status, "cached")
            self.assertIsNone(error)
            self.assertEqual(len(result["raw"]), 608)

    def test_failed_refresh_preserves_cache_and_suppresses_forecast(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            dengue.atomic_json(path, cached(retrieved=NOW - timedelta(days=2)))
            before = path.read_bytes()
            def failed(*args, **kwargs):
                raise URLError("do not publish this private response body")
            result, status, error = dengue.load_data(path, NOW, failed)
            payload = dengue.build_payload(result, status, error, NOW)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(payload["status"], "stale")
            self.assertEqual(payload["forecasts"], [])
            self.assertNotIn("private response", json.dumps(payload))

    def test_missing_source_outputs_valid_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            def failed(*args, **kwargs):
                raise URLError("failure")
            data, status, error = dengue.load_data(Path(directory) / "cache.json", NOW, failed)
            payload = dengue.build_payload(data, status, error, NOW)
            dengue.validate_payload(payload)
            self.assertEqual(payload["status"], "unavailable")

    def test_bounded_response_rejects_excess_data(self):
        with tempfile.TemporaryDirectory() as directory:
            data, status, error = dengue.load_data(Path(directory) / "cache.json", NOW,
                                                  lambda *a, **kw: io.BytesIO(b"x" * (dengue.MAX_BYTES + 1)))
            self.assertIsNone(data)
            self.assertEqual(status, "unavailable")
            self.assertEqual(error, "ValueError")

    def test_network_success_hashes_raw_response_and_atomically_caches(self):
        body = json.dumps(raw_series()).encode()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            data, status, error = dengue.load_data(path, NOW, lambda *a, **kw: io.BytesIO(body))
            self.assertEqual(data["raw_sha256"], hashlib.sha256(body).hexdigest())
            self.assertEqual(status, "fresh")
            self.assertIsNone(error)
            self.assertEqual(json.loads(path.read_text())["raw"], raw_series())


class TemporalEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = dengue.normalize_history(raw_series(), NOW)
        cls.evaluation, cls.live, cls.widths = dengue.evaluate(cls.rows, 2)

    def test_future_cases_and_weather_do_not_change_earlier_prediction(self):
        rows = copy.deepcopy(self.rows)
        cutoff = rows[350]["week"]
        original, _ = dengue.rolling_predictions(rows, 2)
        for row in rows[351:]:
            row.update(cases=999999, temperature_min=59, humidity_max=1)
        altered, _ = dengue.rolling_predictions(rows, 2)
        first = [r["predictions"] for r in original if r["available_week"] <= cutoff]
        second = [r["predictions"] for r in altered if r["available_week"] <= cutoff]
        self.assertEqual(first, second)

    def test_nowcast_is_never_a_target_or_predictor(self):
        raw = raw_series()
        for item in raw:
            item.update(casos_est=1, Rt=999, nivel=4, p_rt1=1)
        revised = dengue.normalize_history(raw, NOW)
        evaluation, live, widths = dengue.evaluate(revised, 2)
        self.assertEqual(evaluation, self.evaluation)
        self.assertEqual(live, self.live)
        self.assertEqual(widths, self.widths)

    def test_test_outcomes_cannot_select_model_or_calibrate_intervals(self):
        rows = copy.deepcopy(self.rows)
        for row in rows:
            if row["week"] >= "2024-01-01":
                row["cases"] = row["cases"] * 100
        evaluation, _, widths = dengue.evaluate(rows, 2)
        self.assertEqual(evaluation["selected_model"], self.evaluation["selected_model"])
        self.assertEqual(evaluation["baseline"], self.evaluation["baseline"])
        self.assertEqual(widths, self.widths)
        self.assertNotEqual(evaluation["heldout"], self.evaluation["heldout"])

    def test_boundaries_embargo_origins_until_selection_and_calibration_known(self):
        recorded = []
        original = dengue.empirical_quantile
        records, _ = dengue.rolling_predictions(self.rows, 2)
        expected = [r for r in records if "2022-01-01" <= r["week"] <= "2023-12-31" and r["available_week"] >= "2022-01-01"]
        with patch.object(dengue, "empirical_quantile", side_effect=lambda values: (recorded.append(len(values)), original(values))[1]):
            evaluation, _, _ = dengue.evaluate(self.rows, 2)
        self.assertEqual(recorded[:4], [sum(r["horizon_weeks"] == h for r in expected) for h in range(1, 5)])
        eligible_test = [r for r in records if "2024-01-01" <= r["week"] <= evaluation["test_period"]["end"] and r["available_week"] >= "2024-01-01"]
        self.assertEqual(evaluation["heldout"]["n"], len(dengue.comparable(eligible_test)))

    def test_baseline_kept_when_candidates_do_not_improve(self):
        rows = copy.deepcopy(self.rows)
        for row in rows:
            row["cases"] = 100
        evaluation, _, _ = dengue.evaluate(rows, 1)
        self.assertEqual(evaluation["selected_model"], "persistence")
        self.assertEqual(evaluation["heldout"]["baseline_mae"], 0)


class PublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = dengue.build_payload(cached(), "fresh", now=NOW)

    def test_ready_payload_has_four_strict_future_weeks_and_delay_horizons(self):
        dengue.validate_payload(self.payload)
        self.assertEqual(self.payload["status"], "ready")
        self.assertEqual(self.payload["origin_week"], "2026-09-06")
        self.assertEqual([r["week"] for r in self.payload["forecasts"]], ["2026-09-13", "2026-09-20", "2026-09-27", "2026-10-04"])
        self.assertEqual([r["data_horizon_weeks"] for r in self.payload["forecasts"]], [3, 4, 5, 6])

    def test_midweek_issue_still_starts_forecasts_in_the_future(self):
        midweek = NOW + timedelta(days=4)
        payload = dengue.build_payload(cached(retrieved=midweek), "fresh", now=midweek)
        dengue.validate_payload(payload)
        self.assertGreater(payload["forecasts"][0]["week"], midweek.date().isoformat())

    def test_old_source_never_issues_forecast(self):
        payload = dengue.build_payload(cached(), "fresh", now=NOW + timedelta(weeks=3))
        self.assertEqual(payload["status"], "stale")
        self.assertFalse(payload["data_quality"]["valid_for_forecast"])
        self.assertEqual(payload["forecasts"], [])

    def test_validator_rejects_past_week_negative_and_inverted_intervals(self):
        for key, value in (("week", "2026-09-06"), ("point", -1), ("lower", 999999), ("upper", float("nan"))):
            payload = copy.deepcopy(self.payload)
            payload["forecasts"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                dengue.validate_payload(payload)

    def test_validator_rejects_forecasts_in_stale_payload(self):
        payload = copy.deepcopy(self.payload)
        payload["status"] = "stale"
        with self.assertRaises(ValueError):
            dengue.validate_payload(payload)

    def test_validator_rejects_stale_source_forged_as_ready(self):
        for field, value in (("status", "stale"), ("retrieved_at", "2026-09-01T05:00:00+00:00"),
                             ("retrieved_at", "2026-09-06T05:00:00"), ("retrieved_at", "2026-09-07T05:00:00+00:00")):
            payload = copy.deepcopy(self.payload)
            payload["source"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                dengue.validate_payload(payload)

    def test_validator_rejects_old_history_and_false_freshness_metadata(self):
        payload = copy.deepcopy(self.payload)
        for row in payload["history"]:
            row["week"] = (date.fromisoformat(row["week"]) - timedelta(weeks=52)).isoformat()
        payload["source"]["data_sha256"] = hashlib.sha256(json.dumps(payload["history"], sort_keys=True,
                                                                       separators=(",", ":")).encode()).hexdigest()
        payload["data_origin_week"] = payload["history"][-1]["week"]
        payload["data_quality"]["latest_week"] = payload["data_origin_week"]
        for forecast in payload["forecasts"]:
            forecast["data_horizon_weeks"] += 52
        with self.assertRaises(ValueError):
            dengue.validate_payload(payload)
        payload = copy.deepcopy(self.payload)
        payload["data_quality"]["latest_reported_cases"] = 999999
        with self.assertRaises(ValueError):
            dengue.validate_payload(payload)


if __name__ == "__main__":
    unittest.main()
