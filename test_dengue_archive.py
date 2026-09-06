"""Archive permissions, data minimization and immutable issuance regressions."""
import base64
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from unittest.mock import patch

from scripts import record_dengue_forecast as archive


def payload():
    return {"schema_version": 1, "status": "ready", "generated_at": datetime.now(timezone.utc).isoformat(),
            "location": {"name": "Rio de Janeiro", "country": "Brazil", "geocode": "3304557"},
            "source": {"name": "InfoDengue", "url": "https://info.dengue.mat.br/api/alertcity", "secret": "PRIVATE"},
            "model_version": "test", "token": "PRIVATE",
            "forecasts": [{"week": "2026-09-13", "horizon_weeks": 1, "data_horizon_weeks": 3,
                           "point": 100, "lower": 10, "upper": 300, "model": "persistence", "secret": "PRIVATE"}],
            "history": [{"week": "2026-08-23", "cases": 95, "temperature_min": 18, "humidity_max": 89,
                         "raw": "PRIVATE"}]}


class ForecastArchiveTests(unittest.TestCase):
    def setUp(self):
        # Payload validation is covered by model tests. These cases isolate the
        # publication trust boundary and GitHub behavior from model computation.
        self.validation = patch.object(archive, "validate_payload").start()
        self.addCleanup(patch.stopall)

    def test_only_aggregate_input_fields_are_preserved(self):
        data = payload()
        record = archive.make_record(data, "a" * 40)
        self.assertNotIn("PRIVATE", json.dumps(record))
        self.assertEqual(record["input_history"][0]["cases"], 95)
        self.assertEqual(record["forecasts"][0]["point"], 100)
        self.assertEqual(record["code_revision"], "a" * 40)
        self.assertEqual(len(record["published_payload_sha256"]), 64)
        self.validation.assert_called_once_with(data)

    def test_not_ready_predictions_are_not_archived(self):
        for status in ("stale", "unavailable"):
            data = payload()
            data["status"] = status
            self.assertIsNone(archive.make_record(data, "a" * 40))

    def test_revision_and_size_limits_are_enforced(self):
        with self.assertRaises(ValueError):
            archive.make_record(payload(), "main")
        with patch.object(archive, "MAX_RECORD_BYTES", 100), self.assertRaises(ValueError):
            archive.make_record(payload(), "a" * 40)

    def test_no_network_outside_actions_main(self):
        for env in ({}, {"GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/heads/feature"}):
            with patch.dict("os.environ", env, clear=True), patch.object(archive.urllib.request, "urlopen") as opener:
                archive.main()
                opener.assert_not_called()

    def run_archive(self, exists):
        calls = []
        def opener(request, timeout):
            calls.append(request)
            if request.get_method() == "GET" and not exists:
                raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)
            return io.BytesIO(b'{}')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "dengue_forecast.json").write_text(json.dumps(payload()))
            env = {"GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": "a" * 40,
                   "GITHUB_REPOSITORY": "owner/project", "GITHUB_TOKEN": "TEST-ONLY"}
            with patch.dict("os.environ", env, clear=True), patch.object(archive, "ROOT", root), \
                    patch.object(archive.urllib.request, "urlopen", side_effect=opener):
                archive.main()
        return calls

    def test_existing_week_is_never_overwritten(self):
        calls = self.run_archive(True)
        self.assertEqual([r.get_method() for r in calls], ["GET"])

    def test_first_ready_week_is_created_without_overwrite_sha(self):
        calls = self.run_archive(False)
        self.assertEqual([r.get_method() for r in calls], ["GET", "PUT"])
        body = json.loads(calls[-1].data)
        self.assertNotIn("sha", body)
        self.assertEqual(body["branch"], "main")
        record = json.loads(base64.b64decode(body["content"]))
        self.assertNotIn("PRIVATE", json.dumps(record))
        self.assertIn("/contents/reports/dengue/", calls[-1].full_url)


if __name__ == "__main__":
    unittest.main()
