"""Unit tests for the GeoSentinel scanner's pure (network-free) logic.

Run with: python -m unittest -v test_scanner
Importing scanner_v2 only defines functions and tables — run_scan() is guarded
by __main__, so no network calls happen during tests."""

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

    def test_earliest_country_wins_across_borders(self):
        loc = gs.geocode("Dengue in Bangkok and a separate cluster in Lagos")
        self.assertEqual(loc["iso"], "TH")

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


if __name__ == "__main__":
    unittest.main()
