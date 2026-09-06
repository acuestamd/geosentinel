"""Synthetic semantic regression cases; not a real-world validation dataset."""

import json
import unittest

from signal_quality import analyze_text, geocode_text


class EventAttributionTests(unittest.TestCase):
    def check_event(self, text, *, country, disease, status="active", triage="review", source="news", title=""):
        result = analyze_text(text, source, title=title)
        self.assertEqual(result["location"]["iso"] if result["location"] else None, country)
        self.assertEqual(result["disease"]["name"] if result["disease"] else None, disease)
        self.assertEqual(result["event_status"], status)
        self.assertEqual(result["triage"], triage)
        return result

    def test_disease_name_cannot_supply_a_country(self):
        self.check_event("Crimean-Congo haemorrhagic fever confirmed in Spain", country="ES", disease="crimean-congo")
        self.check_event("Sudan virus outbreak in Uganda", country="UG", disease="sudan virus")
        self.check_event("Crimean-Congo haemorrhagic fever cases reported", country=None, disease="crimean-congo", triage="context")

    def test_geocode_preserves_larger_country_names(self):
        for text, country in [("Cases in South Sudan", "SS"), ("Cases in Equatorial Guinea", "GQ"),
                              ("Cases in Guinea-Bissau", "GW"), ("Cases in Papua New Guinea", "PG"),
                              ("Cases in the Democratic Republic of the Congo", "CD"),
                              ("Cases in the Republic of the Congo", "CG")]:
            with self.subTest(text=text):
                self.assertEqual(geocode_text(text)["iso"], country)

    def test_bare_congo_is_ambiguous(self):
        self.assertIsNone(geocode_text("Cholera cases in Congo"))
        self.check_event("Cholera cases in Congo", country=None, disease="cholera", status="uncertain", triage="context")

    def test_us_aliases_do_not_match_pronoun(self):
        for place in ["United States", "U.S.", "USA", "US", "Estados Unidos", "EE.UU.", "États-Unis", "Chicago"]:
            with self.subTest(place=place):
                self.check_event("Measles cases reported in " + place, country="US", disease="measles")
        self.assertIsNone(geocode_text("Please tell us about cholera"))

    def test_domains_and_url_paths_are_not_entities(self):
        self.check_event("Measles outbreak in Ghana https://spain.example.org/ebola/india", country="GH", disease="measles")
        self.check_event("Measles outbreak reported https://www.bbc.co.uk/news", country=None, disease="measles", triage="context")
        result = analyze_text("Art show in Spain https://example.org/ebola", "news")
        self.assertIsNone(result["disease"])
        self.assertEqual(result["triage"], "context")

    def test_publisher_and_funder_are_not_event_places(self):
        self.check_event("France 24: Ebola outbreak in Uganda", country="UG", disease="ebola")
        self.check_event("UK charity reports 15 cholera cases in Kenya", country="KE", disease="cholera")
        self.check_event("Cholera outbreak in Kenya funded by Germany", country="KE", disease="cholera", status="context", triage="context")
        self.assertIsNone(geocode_text("Study of cholera funded by Germany"))

    def test_non_ascii_country_and_disease(self):
        self.check_event("Casos de sarampión en España", country="ES", disease="measles")
        self.check_event("Épidémie de fièvre jaune au Brésil", country="BR", disease="yellow fever")

    def test_named_pathogen_owns_its_symptoms_and_aliases(self):
        self.check_event("Lassa fever cases in Nigeria", country="NG", disease="lassa fever")
        self.check_event("Human avian influenza A(H5N1) infection in Vietnam", country="VN", disease="h5n1")
        self.check_event("SARS-CoV-2 infections in France", country="FR", disease="covid")

    def test_negative_pathogen_does_not_override_active_other_event(self):
        result = self.check_event("No Ebola cases in Uganda; dengue outbreak confirmed in Kenya", country="KE", disease="dengue")
        self.assertNotIn("Ebola", result["evidence"]["event_text"])
        self.assertEqual(result["evidence"]["assertions"][0]["event_status"], "negated")

    def test_no_deaths_does_not_negate_cases(self):
        self.check_event("Dengue outbreak in Thailand: 300 cases and no deaths", country="TH", disease="dengue")
        self.check_event("No deaths in 12 dengue cases in Thailand", country="TH", disease="dengue")

    def test_negative_place_is_not_borrowed_by_another_assertion(self):
        self.check_event("No Ebola cases in Uganda; dengue cases confirmed", country=None, disease="dengue", triage="context")

    def test_resolution_headline_survives_historical_body(self):
        title = "Uganda declares its Ebola outbreak over"
        self.check_event(title + ". Ebola had caused 12 cases in Uganda.", title=title,
                         country="UG", disease="ebola", status="resolved", triage="context", source="who")

    def test_negated_headline_survives_inaccurate_background(self):
        title = "Cholera ruled out in Kenya"
        self.check_event(title + ". Earlier reports claimed a cholera outbreak in Kenya.", title=title,
                         country="KE", disease="cholera", status="negated", triage="context")

    def test_multiple_events_do_not_collapse_to_highest_severity(self):
        self.check_event("Ebola outbreak in Uganda; dengue cases in Thailand", country=None, disease=None,
                         status="uncertain", triage="context")
        result = analyze_text("Ebola and cholera cases in Uganda", "news")
        self.assertIsNone(result["disease"])
        self.assertEqual(result["triage"], "context")

    def test_multiple_places_abstain_instead_of_arbitrary_pin(self):
        self.check_event("Cholera outbreaks in Kenya and Tanzania", country=None, disease="cholera", status="uncertain", triage="context")
        self.check_event("Dengue cases in Bangkok and Phuket", country=None, disease="dengue", status="uncertain", triage="context")

    def test_incidental_neighbor_does_not_change_event_country(self):
        self.check_event("Cholera outbreak in DR Congo, spreading toward Uganda", country="CD", disease="cholera")


class TravelerAndEvidenceTests(unittest.TestCase):
    def test_personal_return_with_illness(self):
        for text in ["I came back from Bali sick with dengue", "I returned from Thailand with fever"]:
            with self.subTest(text=text):
                result = analyze_text(text, "reddit")
                self.assertTrue(result["is_traveler"])
                self.assertEqual(result["triage"], "review")

    def test_travel_warning_and_general_outbreak_are_not_traveler_cases(self):
        for text in ["Cholera outbreak in Kenya", "Travel warning: dengue outbreak in Thailand",
                     "If you return from Thailand with fever, seek medical advice",
                     "Ebola prevention advice for travelers to Uganda"]:
            with self.subTest(text=text):
                self.assertFalse(analyze_text(text, "news")["is_traveler"])

    def test_context_and_hypothetical_claims_do_not_enter_review(self):
        for text in ["Ebola vaccine trial in Uganda", "Cholera preparedness workshop in Kenya",
                     "Study reviews the 2014 Ebola outbreak in Liberia", "Cholera could cause an outbreak in Kenya",
                     "Measles outbreak simulation in Ghana"]:
            with self.subTest(text=text):
                self.assertEqual(analyze_text(text, "who")["triage"], "context")

    def test_document_provenance_is_retained_without_probability(self):
        result = analyze_text("Cholera cases confirmed in Kenya", "WHO", "2026-09-05")
        self.assertEqual(result["evidence"]["source"], "who")
        self.assertEqual(result["evidence"]["published"], "2026-09-05")
        self.assertEqual(result["evidence"]["event_text"], "Cholera cases confirmed in Kenya")
        self.assertTrue(result["reasons"])
        self.assertNotIn("confidence", result)
        json.dumps(result)

    def test_empty_malformed_text_is_safe_context(self):
        for text in [None, "", 12, "<p></p>"]:
            with self.subTest(text=text):
                result = analyze_text(text, "reddit")
                self.assertEqual(result["triage"], "context")
                self.assertIsNone(result["disease"])

    def test_unknown_language_and_geography_explicitly_abstain(self):
        result = analyze_text("Unrecognized text", "news")
        self.assertIn("no_recognized_disease", result["reasons"])
        result = analyze_text("Dengue outbreak in an unnamed district", "news")
        self.assertIn("location_not_resolved", result["reasons"])
        self.assertEqual(result["triage"], "context")


class AdditionalSemanticRegressionTests(unittest.TestCase):
    """Patterns observed in feed text, with no assertion about incident truth."""

    def test_historical_and_simulated_counts_are_not_active_reports(self):
        for text in [
            "In 2014, an Ebola outbreak caused 100 cases in Liberia.",
            "Study models 100 cases of cholera in Kenya under a hypothetical scenario.",
            "# Phylogenetic analysis of the 2025 # Ebola # outbreak in the # DRC",
            "Lessons Learned During 2024‒25 Avian # Influenza # H5N1 Virus # Outbreak Response in # USA",
        ]:
            with self.subTest(text=text):
                result = analyze_text(text, "mastodon", "2026-09-05")
                self.assertEqual(result["event_status"], "context")
                self.assertEqual(result["triage"], "context")

    def test_comparison_to_prior_year_does_not_hide_current_cases(self):
        result = analyze_text("New dengue cases in Thailand exceed the 2025 outbreak", "news", "2026-09-05")
        self.assertEqual(result["event_status"], "active")
        self.assertEqual(result["triage"], "review")

    def test_negated_traveler_symptom_is_not_ill_traveler(self):
        result = analyze_text("I returned from Thailand with no fever", "reddit")
        self.assertEqual(result["event_status"], "negated")
        self.assertEqual(result["triage"], "context")
        self.assertFalse(result["is_traveler"])

    def test_recent_zero_count_takes_precedence_over_historical_total(self):
        for current_window in [
            "Last 30 days: 0 cases.",
            "The most recent 30-day window shows 0 cases.",
        ]:
            with self.subTest(current_window=current_window):
                text = "Sudan cholera update: 814 verified cases in the last 90 days. " + current_window + " Prior 30 days: 494 cases."
                result = analyze_text(text, "mastodon", "2026-09-05")
                self.assertEqual(result["event_status"], "negated")
                self.assertEqual(result["triage"], "context")
                self.assertEqual(result["location"]["iso"], "SD")
                self.assertIn("0 cases", result["evidence"]["current_window_excerpt"])
        result = analyze_text("Myanmar recorded zero verified cholera cases in the last 30 days, down from 14 previously", "news")
        self.assertEqual(result["event_status"], "negated")

    def test_recent_zero_deaths_does_not_negate_reported_cases(self):
        for current_window in [
            "Last 30 days: no deaths.",
            "The most recent 30-day window shows no deaths.",
            "The most recent 30-day window shows 0 deaths.",
        ]:
            with self.subTest(current_window=current_window):
                text = "Sudan reports 814 new cholera cases. " + current_window
                result = analyze_text(text, "mastodon", "2026-09-05")
                self.assertEqual(result["event_status"], "active")
                self.assertEqual(result["triage"], "review")
                self.assertNotIn("current_window_excerpt", result["evidence"])

    def test_current_denial_is_not_revived_by_retrospective_sentence(self):
        result = analyze_text("No Ebola cases are currently reported in Liberia. The 2014 Ebola outbreak in Liberia involved 100 cases.", "news", "2026-09-05")
        self.assertEqual(result["triage"], "context")

    def test_foreign_agency_and_political_response_are_not_event_places(self):
        text = "The U.S. Centers for Disease Control reports uncontrolled expansion of the Ebola outbreak."
        result = analyze_text(text, "news")
        self.assertIsNone(result["location"])
        self.assertEqual(result["triage"], "context")
        text = "Face à l’épidémie d’Ebola, la France doit augmenter son engagement contre la propagation des maladies."
        result = analyze_text(text, "mastodon")
        self.assertIsNone(result["location"])
        self.assertEqual(result["triage"], "context")

    def test_damaged_display_url_cannot_add_disease_or_place(self):
        result = analyze_text("Art exhibition. https:// example.org/kenya/ 2026/ebola-in-sudan", "mastodon")
        self.assertIsNone(result["disease"])
        self.assertIsNone(result["location"])
        self.assertEqual(result["triage"], "context")


if __name__ == "__main__":
    unittest.main()
