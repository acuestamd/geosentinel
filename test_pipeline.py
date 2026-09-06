"""Integration regressions for publication, identity, retention and outages."""
import copy
import io
import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import scanner_v2 as scanner
from collectors import Collector, MAX_BYTES
from signal_store import (canonical_url, document_id, deduplicate_documents,
                          merge_retained, normalize_date, validate_output, load_document_cache)

NOW = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)


def report(title="Dengue outbreak in Bangkok, Thailand", url="https://example.org/a", source="news"):
    row = {"title": title, "url": url, "published": "2026-09-04T12:00:00Z"}
    return scanner._process_records([row], source)[0]


class IdentityTests(unittest.TestCase):
    def test_inline_spans_do_not_split_urls_or_words(self):
        text = scanner.plain_text('<p>Ebola <a href="https://www.bbc.co.uk/news"><span>https://</span><span>www.bbc.co.uk/</span><span>news</span></a></p>')
        self.assertEqual(text, 'Ebola https://www.bbc.co.uk/news')
        self.assertIsNone(scanner.geocode(text))

    def test_duplicate_retrievals_do_not_multiply_documents(self):
        signal = report()
        copies = [{**signal, "queries": [q]} for q in ["dengue", "outbreak", "travelhealth", "publichealth"]]
        result = deduplicate_documents(copies)
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]["queries"]), 4)

    def test_distinct_city_reports_survive(self):
        rows = [report(), report("Dengue outbreak in Phuket, Thailand", "https://example.org/b")]
        self.assertEqual(len(scanner.deduplicate(rows)), 2)
        self.assertEqual(len(scanner.compute_hotspots(rows)), 2)

    def test_tracking_parameters_do_not_change_identity(self):
        first = document_id("https://example.org/a?utm_source=x&id=2#section")
        self.assertEqual(first, document_id("https://example.org/a?id=2&utm_campaign=y"))

    def test_different_articles_same_country_survive(self):
        self.assertNotEqual(document_id("https://example.org/a"), document_id("https://example.org/b"))

    def test_nondefault_ports_and_ipv6_preserve_identity(self):
        self.assertNotEqual(document_id("http://example.org:443/a"), document_id("http://example.org/a"))
        self.assertEqual(canonical_url("https://[::1]:443/a"), "https://[::1]/a")

    def test_unsafe_or_credentialed_url_is_not_published(self):
        for url in ("javascript:alert(1)", "https://user:secret@example.org", "https://example.org:bad", "//example.org/a"):
            self.assertEqual(canonical_url(url), "")

    def test_unknown_dates_do_not_become_today(self):
        rows = scanner.process_news([{"title": "Dengue outbreak in Bangkok", "url": "https://example.org/a"}])
        self.assertEqual(rows[0]["published"], "")
        self.assertTrue(rows[0]["retrieved_at"])

    def test_rss_gdelt_and_epoch_dates(self):
        self.assertEqual(normalize_date("20260904T120000Z"), "2026-09-04T12:00:00+00:00")
        self.assertEqual(normalize_date("Fri, 04 Sep 2026 12:00:00 GMT"), "2026-09-04T12:00:00+00:00")
        self.assertEqual(normalize_date("nonsense"), "")
        self.assertEqual(normalize_date(True), "")


class RetentionTests(unittest.TestCase):
    def test_previous_documents_survive_source_outage_without_redating(self):
        old = report()
        old["first_seen"] = "2026-09-04T12:00:00+00:00"
        result = merge_retained([old], [], NOW)
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0]["is_carried_forward"])
        self.assertEqual(result[0]["published"], old["published"])

    def test_expired_and_future_documents_are_not_live(self):
        old, future = report(), report(url="https://example.org/b")
        old["published"] = "2026-01-01T00:00:00Z"
        future["published"] = "2027-01-01T00:00:00Z"
        self.assertEqual(merge_retained([old, future], [], NOW), [])

    def test_rediscovery_preserves_first_seen(self):
        old, new = report(), report()
        old["first_seen"] = "2026-09-01T00:00:00+00:00"
        result = merge_retained([old], [new], NOW)
        self.assertEqual(result[0]["first_seen"], old["first_seen"])
        self.assertFalse(result[0]["is_carried_forward"])

    def test_invalid_cache_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            path.write_text('{"schema_version":"3.0","signals":[{"id":"bad"}]}')
            self.assertEqual(load_document_cache(path)["signals"], [])


class SourceHealthTests(unittest.TestCase):
    def test_rate_limited_hosts_are_not_retried_across_hashtags(self):
        calls = []
        def fail(req, timeout):
            calls.append(req.full_url)
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)
        collector = Collector(opener=fail, sleeper=lambda n: None)
        self.assertEqual(collector.mastodon(), [])
        self.assertEqual(len(calls), 2)  # one request per host for the entire scan

    def test_corrupt_source_health_does_not_break_collector(self):
        self.assertIsNone(Collector({"who": "bad"}).health["who"]["last_success"])
        self.assertIsNone(Collector(["bad"]).health["who"]["last_success"])

    def test_feed_shape_with_no_text_is_not_healthy(self):
        collector = Collector()
        collector.health["who"].update(status="ok", items=1, successful_requests=1)
        fresh = scanner._process_records([{"unexpected": "title"}], "who", diagnostics=collector.health["who"])
        out = scanner.build_snapshot(fresh, {}, collector, NOW)
        self.assertEqual(out["health"]["status"], "unavailable")
        self.assertFalse(out["health"]["official_source_available"])
        self.assertEqual(collector.health["who"]["status"], "error")

    def test_rate_limit_stops_without_repeated_requests(self):
        calls = []
        def fail(req, timeout):
            calls.append(req.full_url)
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)
        collector = Collector(opener=fail, sleeper=lambda n: None)
        self.assertEqual(collector.news(), [])
        self.assertEqual(len(calls), 1)
        self.assertEqual(collector.health["news"]["status"], "error")

    def test_disabled_reddit_is_explicit(self):
        with patch.dict("os.environ", {}, clear=True):
            collector = Collector()
            self.assertEqual(collector.reddit(), [])
            self.assertEqual(collector.health["reddit"]["status"], "disabled")

    def test_success_after_error_remains_partial(self):
        collector = Collector(opener=lambda *a, **k: io.BytesIO(b'{"value":[]}'))
        collector.error("who", "Connection failed or timed out")
        collector.who()
        self.assertEqual(collector.health["who"]["status"], "partial")

    def test_shape_change_is_visible(self):
        collector = Collector(opener=lambda *a, **k: io.BytesIO(b'{"unexpected":[]}'))
        self.assertEqual(collector.who(), [])
        self.assertIn("Missing expected item list", collector.health["who"]["errors"])

    def test_oversized_response_is_rejected(self):
        collector = Collector(opener=lambda *a, **k: io.BytesIO(b" " * (MAX_BYTES + 1)))
        self.assertIsNone(collector.request("who", "https://example.org"))
        self.assertEqual(collector.health["who"]["status"], "error")

    def test_all_outage_snapshot_is_unavailable(self):
        collector = Collector()
        for source in collector.health:
            collector.error(source, "Connection failed")
        out = scanner.build_snapshot([], {}, collector, NOW)
        self.assertEqual(out["health"]["status"], "unavailable")

    def test_partial_failure_has_source_level_explanation(self):
        collector = Collector()
        for row in collector.health.values():
            row["status"] = "disabled"
        collector.health["who"].update(status="ok", items=1, successful_requests=1)
        collector.health["news"].update(status="error", errors=["HTTP 429"])
        out = scanner.build_snapshot([report()], {}, collector, NOW)
        self.assertEqual(out["health"]["status"], "degraded")
        self.assertTrue(out["health"]["official_source_available"])


class PublicationTests(unittest.TestCase):
    def test_resolved_not_in_review_queue(self):
        row = report("Uganda declares its Ebola outbreak over")
        self.assertEqual(row["triage"], "context")
        self.assertEqual(row["event_status"], "resolved")

    def test_domain_does_not_create_uk_outbreak(self):
        rows = scanner.process_mastodon([{"content": "Ebola outbreak on track to be deadliest ever https://www.bbc.co.uk/news/articles/story", "url": "https://mastodon.social/@test/1", "created_at": "2026-09-04T12:00:00Z"}])
        self.assertTrue(rows)
        self.assertIsNone(rows[0]["location"])

    def test_automated_records_never_mark_verified(self):
        row = report()
        collector = Collector()
        out = scanner.build_snapshot([row], {}, collector, NOW)
        out["signals"][0]["verification_status"] = "verified"
        with self.assertRaises(ValueError):
            validate_output(out)

    def test_counts_come_from_selected_event_passage(self):
        row = report("No Ebola cases in Uganda. Dengue outbreak in Brazil with 12 cases.")
        self.assertEqual(row["disease"], "dengue")
        self.assertEqual(row["location"]["iso"], "BR")
        self.assertEqual(row["case_count"], 12)


if __name__ == "__main__":
    unittest.main()
