"""Network-free evaluation of fixed synthetic labels and metric accounting."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

import evaluate


def sample_case(ident, status="active", triage="review", country="KE"):
    return {"id": ident, "category": "metric_test", "text": ident,
            "source": "GDELT", "rationale": "Synthetic metric-accounting fixture.",
            "expected": {"event_status": status, "triage": triage,
                         "disease": "cholera", "location_iso": country,
                         "is_traveler": False}}


def prediction(status="active", triage="review", country="KE"):
    return {"event_status": status, "triage": triage,
            "disease": {"name": "cholera"},
            "location": {"iso": country} if country else None,
            "is_traveler": False, "reasons": [], "evidence": {},
            "location_candidates": []}


class EvaluationAccountingTests(unittest.TestCase):
    def test_wrong_country_and_abstention_are_not_removed_from_denominators(self):
        cases = [sample_case("correct"), sample_case("wrong"),
                 sample_case("abstained"), sample_case("unknown", country=None),
                 sample_case("invented", country=None)]
        outputs = {"correct": prediction(), "wrong": prediction(country="UG"),
                   "abstained": prediction(country=None),
                   "unknown": prediction(country=None), "invented": prediction()}
        report = evaluate.evaluate_cases(cases, lambda text, *_args, **_kwargs: outputs[text])
        geo = report["metrics"]["geography"]
        self.assertEqual(geo["precision"], evaluate.fraction(1, 3))
        self.assertEqual(geo["recall"], evaluate.fraction(1, 3))
        self.assertEqual(geo["required_abstention_accuracy"], evaluate.fraction(1, 2))
        self.assertEqual(geo["abstained"], 2)
        self.assertEqual(geo["abstained_locatable"], 1)
        self.assertFalse(report["gates"]["required_geographic_abstention_100pct"])

    def test_review_precision_and_recall_count_false_positives_and_misses(self):
        cases = [sample_case("hit"), sample_case("miss"),
                 sample_case("false_alarm", "context", "context"),
                 sample_case("rejected", "negated", "context")]
        outputs = {"hit": prediction(), "miss": prediction(triage="context"),
                   "false_alarm": prediction(),
                   "rejected": prediction("negated", "context")}
        report = evaluate.evaluate_cases(cases, lambda text, *_args, **_kwargs: outputs[text])
        review = report["metrics"]["review"]
        self.assertEqual({key: review[key] for key in ("tp", "fp", "tn", "fn")},
                         {"tp": 1, "fp": 1, "tn": 1, "fn": 1})
        self.assertEqual(review["precision"], evaluate.fraction(1, 2))
        self.assertEqual(review["recall"], evaluate.fraction(1, 2))
        self.assertEqual(report["safety_violations"], ["false_alarm"])

    def test_protected_case_cannot_escape_gate_by_using_uncertain_review(self):
        cases = [sample_case("resolved", "resolved", "context")]
        report = evaluate.evaluate_cases(cases, lambda *_a, **_kw: prediction("uncertain", "review"))
        self.assertEqual(report["safety_violations"], ["resolved"])
        self.assertFalse(report["passed"])

    def test_false_active_status_fails_even_if_review_is_withheld(self):
        cases = [sample_case("negation", "negated", "context")]
        report = evaluate.evaluate_cases(cases, lambda *_a, **_kw: prediction("active", "context"))
        self.assertEqual(report["safety_violations"], ["negation"])

    def test_no_assigned_locations_is_undefined_precision_not_perfection(self):
        report = evaluate.evaluate_cases([sample_case("miss")],
                                         lambda *_a, **_kw: prediction(country=None))
        self.assertIsNone(report["metrics"]["geography"]["precision"]["value"])
        self.assertFalse(report["gates"]["country_precision_at_least_95pct"])

    def test_missing_explanations_fail_output_contract(self):
        output = prediction()
        output.pop("reasons")
        report = evaluate.evaluate_cases([sample_case("bad_contract")], lambda *_a, **_kw: output)
        self.assertFalse(report["gates"]["valid_output_contract"])

    def test_malformed_location_is_not_accepted_as_a_valid_abstention(self):
        output = prediction(country=None)
        output["location"] = "unresolved"
        report = evaluate.evaluate_cases([sample_case("bad_location", country=None)],
                                         lambda *_a, **_kw: output)
        self.assertFalse(report["gates"]["valid_output_contract"])
        self.assertEqual(report["schema_violations"][0]["fields"], ["location"])

    def test_duplicate_ids_rejected(self):
        corpus = {"kind": "synthetic_regression", "cases": [sample_case("same"), sample_case("same")]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text(json.dumps(corpus), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                evaluate.load_corpus(path)


class SyntheticRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from signal_quality import analyze_text
        cls.corpus = evaluate.load_corpus()
        cls.report = evaluate.evaluate_cases(cls.corpus["cases"], analyze_text)

    def test_corpus_discloses_its_synthetic_origin(self):
        self.assertEqual(self.corpus["kind"], "synthetic_regression")
        self.assertIn("not independent epidemiological validation", self.corpus["labeling"])
        self.assertGreaterEqual(len(self.corpus["cases"]), 35)
        self.assertLessEqual(len(self.corpus["cases"]), 60)

    def test_each_annotated_regression(self):
        for row in self.report["results"]:
            with self.subTest(case=row["id"]):
                self.assertEqual(row["mismatches"], {}, row["mismatches"])

    def test_release_gates(self):
        self.assertTrue(self.report["passed"], evaluate.render_report(self.report))

    def test_evaluation_does_not_mutate_labels(self):
        from signal_quality import analyze_text
        original = copy.deepcopy(self.corpus)
        evaluate.evaluate_cases(self.corpus["cases"], analyze_text)
        self.assertEqual(self.corpus, original)


if __name__ == "__main__":
    unittest.main()
