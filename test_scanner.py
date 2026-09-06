"""Unit tests for the GeoSentinel scanner's pure (network-free) logic.

Run with: python -m unittest -v test_scanner
Importing scanner_v2 only defines functions and tables — run_scan() is guarded
by __main__, so no network calls happen during tests."""

import os
import tempfile
import unittest
import scanner_v2 as gs


class GeocodeTests(unittest.TestCase):
    def test_single_location(self):
        self.assertEqual(
            gs.geocode("Ebola in the Democratic Republic of the Congo")["iso"], "CD")

    def test_primary_location_beats_passing_mention(self):
        # The outbreak is in DR Congo; Uganda is only named as a neighbour.
        # A first-match-wins scan returned Uganda (it sorts earlier in GEO_DB);
        # earliest-mention resolution must return DR Congo.
        loc = gs.geocode(
            "Cholera outbreak in the Democratic Republic of the Congo "
            "spreads toward neighbouring Uganda")
        self.assertEqual(loc["iso"], "CD")

    def test_city_preferred_over_its_country(self):
        loc = gs.geocode("Dengue cases surge in Bangkok, Thailand")
        self.assertEqual(loc["name"], "Bangkok")

    def test_ambiguous_cross_border_text_abstains(self):
        loc = gs.geocode("Dengue in Bangkok and a separate cluster in Lagos")
        self.assertIsNone(loc)  # Two plausible event locations need analyst review.

    def test_no_location_returns_none(self):
        self.assertIsNone(gs.geocode("a general statement about public health"))

    def test_short_key_word_boundary(self):
        # 'car' (Central African Republic key) must not match inside 'cargo'.
        self.assertIsNone(gs.geocode("a cargo ship was delayed at the port"))


class DiseaseTests(unittest.TestCase):
    def test_detects_disease(self):
        found = gs.detect_diseases("a measles outbreak was reported")
        self.assertTrue(any(d["name"] == "measles" for d in found))

    def test_sorted_by_severity(self):
        found = gs.detect_diseases("reports mention both dengue and ebola")
        self.assertEqual(found[0]["name"], "ebola")  # sev 10 outranks dengue's 6

    def test_no_disease(self):
        self.assertEqual(gs.detect_diseases("the weather was pleasant"), [])


class ExtractCountTests(unittest.TestCase):
    def test_pulls_cases_and_deaths(self):
        self.assertEqual(
            gs.extract_counts("12 confirmed cases and 3 deaths"),
            {"cases": 12, "deaths": 3})

    def test_strips_thousands_separators(self):
        self.assertEqual(gs.extract_counts("1,200 cases")["cases"], 1200)

    def test_rejects_implausibly_large(self):
        # > 10M is rejected as a likely population/ID/year-range artifact.
        self.assertEqual(gs.extract_counts("a region of 50000000 cases"), {})

    def test_no_counts(self):
        self.assertEqual(gs.extract_counts("dozens were affected"), {})


class TravelerSignalTests(unittest.TestCase):
    def test_traveler_phrasing(self):
        self.assertTrue(
            gs.is_traveler_signal("I came back from Thailand sick with a fever"))

    def test_non_traveler(self):
        self.assertFalse(gs.is_traveler_signal("the museum was lovely today"))


class DateNormalizationTests(unittest.TestCase):
    def test_rfc822_to_iso(self):
        iso = gs._to_iso("Wed, 11 Jun 2026 14:03:00 GMT")
        self.assertTrue(iso.startswith("2026-06-11T14:03:00"))

    def test_empty(self):
        self.assertEqual(gs._to_iso(""), "")
        self.assertEqual(gs._to_iso(None), "")

    def test_unparseable_passthrough(self):
        self.assertEqual(gs._to_iso("not a date"), "not a date")


class ExtractCountExtraTests(unittest.TestCase):
    def test_million_multiplier(self):
        self.assertEqual(gs.extract_counts("2 million cases")["cases"], 2_000_000)

    def test_thousand_multiplier(self):
        self.assertEqual(gs.extract_counts("reported 500 thousand cases")["cases"], 500_000)

    def test_nbsp_grouped_thousands(self):
        # Real typographic grouping (nbsp) groups; a plain ASCII space does not,
        # so "day 3 200 cases" is not misread as 3200.
        self.assertEqual(gs.extract_counts("1 200 cases")["cases"], 1200)

    def test_ascii_space_is_not_a_thousands_separator(self):
        self.assertEqual(gs.extract_counts("on day 3 200 cases")["cases"], 200)
        self.assertEqual(gs.extract_counts("COVID-19 200 cases reported")["cases"], 200)

    def test_million_over_cap_rejected(self):
        self.assertEqual(gs.extract_counts("50 million cases"), {})


class DiseaseTaxonomyTests(unittest.TestCase):
    def test_new_terms_detected(self):
        for term, expected in [("H7N9 detected in poultry", "h7n9"),
                               ("a mystery illness cluster", "mystery illness"),
                               ("whooping cough cases rise", "whooping cough"),
                               ("Sudan virus disease confirmed", "sudan virus")]:
            with self.subTest(term=term):
                self.assertTrue(any(d["name"] == expected for d in gs.detect_diseases(term)))

    def test_same_category_diseases_both_survive(self):
        # The removed category-dedup must not have changed this: both survive.
        names = {d["name"] for d in gs.detect_diseases("tuberculosis and covid reported")}
        self.assertLessEqual({"tuberculosis", "covid"}, names)

    def test_most_severe_first(self):
        self.assertEqual(gs.detect_diseases("dengue and ebola")[0]["name"], "ebola")


class AnomalyTests(unittest.TestCase):
    def test_score_cold_cache(self):
        self.assertFalse(gs.score_anomaly(1, 0))      # no baseline -> not a surge

    def test_score_noise_floor(self):
        self.assertFalse(gs.score_anomaly(2, 1))      # below ANOMALY_MIN_COUNT

    def test_score_surge(self):
        self.assertTrue(gs.score_anomaly(5, 1))       # clears Poisson band

    def test_score_steady(self):
        self.assertFalse(gs.score_anomaly(3, 3))

    def test_surge_flags_anomaly_without_severity_bump(self):
        sigs = [{"location": {"iso": "US"}, "disease": "dengue", "severity": 6, "confidence": 0.7}]
        hist = {"scans": [], "baselines": {"US:dengue": {"avg_signals_per_scan": 1.0, "samples": 5}}}
        out = gs.detect_anomalies(sigs, hist, {"US:dengue": 5})
        self.assertTrue(out[0]["anomaly"])
        self.assertFalse(out[0]["is_new"])
        self.assertEqual(out[0]["severity"], 6)       # severity is NOT mutated anymore

    def test_cold_cache_is_novelty_not_anomaly(self):
        # The regression that mattered: an empty baseline must NOT flag everything.
        sigs = [{"location": {"iso": "BR"}, "disease": "zika", "severity": 5, "confidence": 0.6}]
        out = gs.detect_anomalies(sigs, {"scans": [], "baselines": {}}, {"BR:zika": 1})
        self.assertFalse(out[0]["anomaly"])
        self.assertTrue(out[0]["is_new"])

    def test_legacy_avg_weekly_reseeds_not_false_surge(self):
        # A legacy post-dedup baseline is on a different (smaller) scale, so it
        # must NOT be read as a surge baseline — that would fire false surges on
        # the first warm-cache scan after deploy. The pair re-seeds as new.
        hist = {"scans": [], "baselines": {"IN:nipah": {"avg_weekly": 1.0, "samples": 3}}}
        out = gs.detect_anomalies([{"location": {"iso": "IN"}, "disease": "nipah", "severity": 9, "confidence": 0.9}],
                                  hist, {"IN:nipah": 6})
        self.assertFalse(out[0]["anomaly"])
        self.assertTrue(out[0]["is_new"])
        self.assertEqual(hist["baselines"]["IN:nipah"]["avg_signals_per_scan"], 6.0)
        self.assertNotIn("avg_weekly", hist["baselines"]["IN:nipah"])


class HistoryCacheTests(unittest.TestCase):
    def setUp(self):
        self._orig = gs.HISTORY_FILE
        fd, self.path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        gs.HISTORY_FILE = self.path

    def tearDown(self):
        gs.HISTORY_FILE = self._orig
        for p in (self.path, self.path + ".tmp"):
            if os.path.exists(p):
                os.remove(p)

    def test_truncated_cache_self_heals(self):
        with open(self.path, "w") as f:
            f.write("{truncated")
        self.assertEqual(gs.load_history(), {"scans": [], "baselines": {}})

    def test_wrong_shape_self_heals(self):
        with open(self.path, "w") as f:
            f.write("[1, 2, 3]")
        self.assertEqual(gs.load_history(), {"scans": [], "baselines": {}})

    def test_atomic_write_round_trips_and_leaves_no_tmp(self):
        gs._atomic_write_json(self.path, {"scans": [], "baselines": {"x": 1}}, indent=2)
        self.assertEqual(gs.load_history()["baselines"], {"x": 1})
        self.assertFalse(os.path.exists(self.path + ".tmp"))


class FaultToleranceTests(unittest.TestCase):
    def test_process_who_none_fields(self):
        self.assertEqual(gs.process_who([{"Name": None, "Description": None}]), [])

    def test_process_who_skips_poison_keeps_valid(self):
        items = [{"Name": None, "Description": 123},  # poison: Description is an int
                 {"Name": "Ebola in the Democratic Republic of the Congo",
                  "Description": "12 cases", "PublicationDate": "2026-06-01", "UrlName": "x"}]
        out = gs.process_who(items)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["location"]["iso"], "CD")

    def test_process_news_none_title(self):
        self.assertEqual(gs.process_news([{"title": None}]), [])

    def test_process_reddit_none_fields(self):
        self.assertEqual(gs.process_reddit([{"title": None, "description": None}]), [])

    def test_process_mastodon_non_list(self):
        self.assertEqual(gs.process_mastodon({"error": "rate limited"}), [])

    def test_process_mastodon_skips_non_dict_and_none_content(self):
        statuses = ["not a dict", {"content": None}, {"content": "<p>dengue outbreak in Bangkok</p>"}]
        out = gs.process_mastodon(statuses)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["location"]["name"], "Bangkok")

    def test_systematic_breakage_warns_loudly(self):
        # A feed reshape (every item a poison int) should warn, not go silently empty.
        import io
        from contextlib import redirect_stderr
        buf = io.StringIO()
        with redirect_stderr(buf):
            out = gs.process_who([{"Name": None, "Description": 1} for _ in range(6)])
        self.assertEqual(out, [])
        self.assertIn("possible upstream format change", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
