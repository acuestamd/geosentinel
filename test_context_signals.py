import copy
import io
import json
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone

from context_signals import enrich_context, MAX_RESPONSE_BYTES
from signal_quality import geocode_text

NOW = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)


def signal(place="Bangkok", disease="dengue"):
    return {"disease": disease, "location": geocode_text("Dengue in " + place),
            "triage": "review", "event_status": "active", "published": "2026-09-04T00:00:00Z"}


def payload():
    dates = [(NOW.date() + timedelta(days=i)).isoformat() for i in range(-7, 7)]
    return {"latitude": 13.75, "longitude": 100.5, "utc_offset_seconds": 0,
            "daily_units": {"temperature_2m_mean": "°C", "precipitation_sum": "mm"},
            "hourly_units": {"relative_humidity_2m": "%"},
            "daily": {"time": dates, "temperature_2m_mean": [28] * 14, "precipitation_sum": [3] * 14},
            "hourly": {"time": [d + f"T{h:02}:00" for d in dates for h in range(24)],
                       "relative_humidity_2m": [70] * 336}}


class WeatherContextTests(unittest.TestCase):
    def test_full_periods_units_and_inputs_unchanged(self):
        source = signal()
        original = copy.deepcopy(source)
        output, cache = enrich_context([source], opener=lambda *a, **k: io.BytesIO(json.dumps(payload()).encode()), now=NOW)
        weather = output[0]["context"]["weather"]
        self.assertEqual(source, original)
        self.assertEqual(weather["status"], "available")
        self.assertEqual(weather["periods"]["recent"]["end"], "2026-09-04")
        self.assertEqual(weather["periods"]["forecast"]["start"], "2026-09-05")
        self.assertEqual(weather["periods"]["forecast"]["end"], "2026-09-11")
        self.assertEqual(weather["periods"]["recent"]["precipitation_total_mm"], 21)
        self.assertEqual(weather["periods"]["forecast"]["relative_humidity_mean_pct"], 70)
        self.assertEqual(output[0]["context"]["forecast"]["status"], "not_estimated")
        self.assertEqual(output[0]["context"]["mobility"]["status"], "not_connected")

    def test_country_and_island_centroids_do_not_request_weather(self):
        calls = []
        output, _ = enrich_context([signal("Thailand"), signal("Bali")], opener=lambda *a, **k: calls.append(a), now=NOW)
        self.assertEqual(calls, [])
        self.assertTrue(all(s["context"]["weather"]["status"] == "needs_locality" for s in output))

    def test_cache_and_document_duplicates_use_one_request(self):
        calls = []
        def open_url(*args, **kwargs):
            calls.append(args)
            return io.BytesIO(json.dumps(payload()).encode())
        output, cache = enrich_context([signal(), signal()], opener=open_url, now=NOW)
        output, _ = enrich_context([signal()], cache, opener=open_url, now=NOW + timedelta(hours=1))
        self.assertEqual(len(calls), 1)
        self.assertTrue(output[0]["context"]["weather"]["cached"])

    def test_missing_rainfall_is_unknown_not_zero(self):
        data = payload()
        data["daily"]["precipitation_sum"][0] = None
        output, _ = enrich_context([signal()], opener=lambda *a, **k: io.BytesIO(json.dumps(data).encode()), now=NOW)
        weather = output[0]["context"]["weather"]
        self.assertEqual(weather["status"], "partial")
        self.assertIsNone(weather["periods"]["recent"]["precipitation_total_mm"])

    def test_missing_humidity_hour_invalidates_daily_mean(self):
        data = payload()
        data["hourly"]["relative_humidity_2m"][0] = None
        output, _ = enrich_context([signal()], opener=lambda *a, **k: io.BytesIO(json.dumps(data).encode()), now=NOW)
        self.assertIsNone(output[0]["context"]["weather"]["periods"]["recent"]["relative_humidity_mean_pct"])

    def test_unverified_units_rejected(self):
        data = payload()
        del data["daily_units"]
        output, _ = enrich_context([signal()], opener=lambda *a, **k: io.BytesIO(json.dumps(data).encode()), now=NOW)
        self.assertEqual(output[0]["context"]["weather"]["status"], "unavailable")

    def test_corrupt_cache_and_oversized_response_do_not_block_signals(self):
        output, _ = enrich_context([signal()], cache={"version": 1, "sites": ["bad"]}, opener=lambda *a, **k: io.BytesIO(b"x" * (MAX_RESPONSE_BYTES + 1)), now=NOW)
        self.assertEqual(output[0]["context"]["weather"]["status"], "unavailable")
        self.assertEqual(output[0]["triage"], "review")

    def test_rate_limit_stops_other_city_requests(self):
        calls = []
        def fail(request, timeout):
            calls.append(request)
            raise urllib.error.HTTPError(request.full_url, 429, "rate limited", {}, None)
        output, _ = enrich_context([signal("Bangkok"), signal("Lagos")], opener=fail, now=NOW)
        self.assertEqual(len(calls), 1)
        self.assertTrue(all(s["context"]["weather"]["status"] == "unavailable" for s in output))


if __name__ == "__main__":
    unittest.main()
