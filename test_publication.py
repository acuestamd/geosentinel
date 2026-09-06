"""Publication boundary regressions using temporary files and mocked HTTP only."""

import base64
import copy
import hashlib
import io
import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import build_site, record_operations
from dengue_forecast import build_payload

NOW = datetime(2026, 9, 6, 12, tzinfo=timezone.utc)


def snapshot():
    return {"schema_version": "3.0", "lastScan": NOW.isoformat(), "signals": [],
            "health": {"status": "healthy", "sources": [
                {"id": "who", "status": "ok", "items": 1, "signals": 0,
                 "errors": [], "last_success": NOW.isoformat()}]},
            "stats": {"review_signals": 0}}


class StaticArtifactTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.destination = self.root / "_site"
        for name, body in (("index.html", "<h1>Public dashboard</h1>"),
                           ("dashboard.js", "'use strict';"), ("LICENSE", "License text"),
                           ("dengue-pilot.js", "'use strict';"),
                           ("dengue_forecast.json", json.dumps(build_payload(None, "unavailable", now=NOW))),
                           ("signals.json", json.dumps(snapshot())),
                           ("dengue_history_cache.json", "PRIVATE PROVIDER CACHE MARKER"),
                           ("signal_documents.json", "PRIVATE CACHE MARKER"),
                           (".env", "PRIVATE CREDENTIAL MARKER"),
                           ("scanner_v2.py", "PRIVATE RUNNER SOURCE MARKER")):
            (self.root / name).write_text(body, encoding="utf-8")
        self.addCleanup(patch.stopall)
        patch.object(build_site, "ROOT", self.root).start()
        patch.object(build_site.subprocess, "check_output", return_value="a" * 40 + "\n").start()

    def test_artifact_contains_only_public_allowlist_and_manifest(self):
        self.destination.mkdir()
        (self.destination / "leftover-secret.txt").write_text("PRIVATE PREVIOUS BUILD MARKER")
        build_site.build()
        self.assertEqual({file.name for file in self.destination.iterdir()},
                         {"index.html", "dashboard.js", "dengue-pilot.js", "signals.json", "dengue_forecast.json", "LICENSE",
                          ".nojekyll", "manifest.json"})
        for file in self.destination.iterdir():
            self.assertNotIn(b"PRIVATE", file.read_bytes())
        # Building a public artifact must not alter or remove its private inputs.
        self.assertTrue((self.root / ".env").exists())
        self.assertTrue((self.root / "signal_documents.json").exists())

    def test_manifest_hashes_exact_published_bytes_and_records_revision(self):
        manifest = build_site.build()
        self.assertEqual(manifest["revision"], "a" * 40)
        self.assertEqual(manifest["lastScan"], NOW.isoformat())
        for name, expected_hash in manifest["files"].items():
            self.assertEqual(hashlib.sha256((self.destination / name).read_bytes()).hexdigest(),
                             expected_hash)
        self.assertEqual(json.loads((self.destination / "manifest.json").read_text()), manifest)

    def test_unavailable_scan_is_refused_before_existing_artifact_is_removed(self):
        self.destination.mkdir()
        sentinel = self.destination / "index.html"
        sentinel.write_text("Previous good artifact")
        data = snapshot()
        data["health"]["status"] = "unavailable"
        (self.root / "signals.json").write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "unavailable"):
            build_site.build()
        self.assertEqual(sentinel.read_text(), "Previous good artifact")

    def test_invalid_schema_cannot_be_built(self):
        data = snapshot()
        data["schema_version"] = "obsolete"
        (self.root / "signals.json").write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            build_site.build()
        self.assertFalse(self.destination.exists())

    def test_invalid_dengue_payload_preserves_previous_artifact(self):
        self.destination.mkdir()
        sentinel = self.destination / "index.html"
        sentinel.write_text("Previous good artifact")
        (self.root / "dengue_forecast.json").write_text('{"schema_version": 999}')
        with self.assertRaises(ValueError):
            build_site.build()
        self.assertEqual(sentinel.read_text(), "Previous good artifact")

    def test_unavailable_dengue_does_not_remove_global_evidence_workspace(self):
        manifest = build_site.build()
        self.assertEqual(manifest["dengue"]["status"], "unavailable")
        self.assertTrue((self.destination / "signals.json").exists())
        payload = json.loads((self.destination / "dengue_forecast.json").read_text())
        self.assertEqual(payload["forecasts"], [])


class OperationalAuditTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "signals.json").write_text(json.dumps(snapshot()))

    def test_public_audit_excludes_source_text_urls_and_credentials(self):
        data = snapshot()
        data["signals"] = [{"summary": "PRIVATE PATIENT TEXT", "url": "PRIVATE SOURCE URL",
                            "evidence": {"raw": "PRIVATE FULL CONTENT"}}]
        data["token"] = "PRIVATE TOKEN"
        original = copy.deepcopy(data)
        entry = record_operations.audit_entry(data, NOW)
        encoded = json.dumps(entry)
        self.assertNotIn("PRIVATE", encoded)
        self.assertEqual(entry["documents"], 1)
        self.assertEqual(entry["week"], "2026-W36")
        self.assertIn("not independent epidemiological validation", entry["validation_scope"])
        self.assertEqual(data, original)

    def test_audit_week_uses_iso_week_year_at_new_year(self):
        entry = record_operations.audit_entry(snapshot(), datetime(2027, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(entry["week"], "2026-W53")

    def test_audit_does_not_access_network_outside_actions_main(self):
        for env in ({}, {"GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/heads/feature"},
                    {"GITHUB_ACTIONS": "false", "GITHUB_REF": "refs/heads/main"}):
            with self.subTest(env=env), patch.dict("os.environ", env, clear=True), \
                    patch.object(record_operations.urllib.request, "urlopen") as opener:
                record_operations.main()
                opener.assert_not_called()

    def run_main(self, previous=None, missing=False):
        requests = []
        def urlopen(request, timeout):
            requests.append(request)
            if request.get_method() == "GET":
                if missing:
                    raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)
                stored = {"audits": previous or []}
                return io.BytesIO(json.dumps({"sha": "existing-sha", "content":
                    base64.b64encode(json.dumps(stored).encode()).decode()}).encode())
            return io.BytesIO(b'{}')

        env = {"GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/heads/main",
               "GITHUB_REPOSITORY": "owner/project", "GITHUB_TOKEN": "TEST-ONLY-NOT-A-SECRET"}
        fixed_entry = record_operations.audit_entry(snapshot(), NOW)
        with patch.dict("os.environ", env, clear=True), \
                patch.object(record_operations, "__file__", str(self.root / "scripts" / "record_operations.py")), \
                patch.object(record_operations, "audit_entry", return_value=fixed_entry), \
                patch.object(record_operations.urllib.request, "urlopen", side_effect=urlopen):
            record_operations.main()
        return requests

    def test_already_recorded_week_performs_no_write(self):
        requests = self.run_main([{"week": "2026-W36"}])
        self.assertEqual([r.get_method() for r in requests], ["GET"])

    def test_missing_audit_file_is_created_on_main_without_raw_signals(self):
        requests = self.run_main(missing=True)
        self.assertEqual([r.get_method() for r in requests], ["GET", "PUT"])
        self.assertEqual(requests[1].full_url,
                         "https://api.github.com/repos/owner/project/contents/reports/operations.json")
        payload = json.loads(requests[1].data)
        self.assertEqual(payload["branch"], "main")
        self.assertNotIn("sha", payload)
        stored = json.loads(base64.b64decode(payload["content"]))
        self.assertEqual(len(stored["audits"]), 1)
        self.assertNotIn("TEST-ONLY-NOT-A-SECRET", json.dumps(stored))

    def test_history_is_bounded_and_existing_sha_is_used(self):
        previous = [{"week": f"old-{index}"} for index in range(70)]
        requests = self.run_main(previous)
        payload = json.loads(requests[1].data)
        self.assertEqual(payload["sha"], "existing-sha")
        audits = json.loads(base64.b64decode(payload["content"]))["audits"]
        self.assertEqual(len(audits), 52)
        self.assertEqual(audits[0]["week"], "old-19")
        self.assertEqual(audits[-1]["week"], "2026-W36")


if __name__ == "__main__":
    unittest.main()
