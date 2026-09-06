#!/usr/bin/env python3
"""Offline, synthetic regression evaluation; not epidemiological validation.

Run ``python evaluate.py --check`` for release gates, or ``--json`` for the
full machine-readable report. The evaluator never collects live data.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

DEFAULT_CORPUS = Path(__file__).parent / "fixtures" / "triage_cases.json"
PROTECTED_STATUSES = {"resolved", "negated", "context"}
STATUSES = PROTECTED_STATUSES | {"active", "uncertain"}


def fraction(numerator, denominator):
    """Keep undefined metrics undefined instead of silently calling them 100%."""
    return {"numerator": numerator, "denominator": denominator,
            "value": numerator / denominator if denominator else None}


def load_corpus(path=DEFAULT_CORPUS):
    with open(path, encoding="utf-8") as handle:
        corpus = json.load(handle)
    if corpus.get("kind") != "synthetic_regression":
        raise ValueError("This evaluator requires a labeled synthetic_regression corpus")
    cases = corpus.get("cases", [])
    seen = set()
    for case in cases:
        ident = case["id"]
        if ident in seen:
            raise ValueError("Duplicate fixture id: " + ident)
        seen.add(ident)
        expected = case["expected"]
        if set(expected) - {"event_status", "triage", "disease", "location_iso", "is_traveler"}:
            raise ValueError("Unknown expected label dimension: " + ident)
        if expected["event_status"] not in STATUSES:
            raise ValueError("Invalid expected event status: " + ident)
        if expected["triage"] not in {"review", "context"}:
            raise ValueError("Invalid expected triage: " + ident)
        if not isinstance(expected["is_traveler"], bool):
            raise ValueError("Expected traveler label must be boolean: " + ident)
        if "location_iso" not in expected:
            raise ValueError("Label a country or explicit geographic abstention: " + ident)
        if not case.get("rationale"):
            raise ValueError("Missing labeling rationale: " + ident)
        if expected["event_status"] in PROTECTED_STATUSES and expected["triage"] == "review":
            raise ValueError("Protected fixture must not enter review: " + ident)
    if not cases:
        raise ValueError("Corpus must contain labeled cases")
    return corpus


def evaluate_cases(cases, analyzer):
    """Compare an injected text analyzer with fixed, independently stored labels."""
    confusion = Counter({"tp": 0, "fp": 0, "tn": 0, "fn": 0})
    dimension_totals, dimension_correct = Counter(), Counter()
    geography = Counter({"assigned": 0, "correct_assignments": 0,
                         "locatable": 0, "abstained": 0,
                         "abstained_locatable": 0, "abstention_required": 0,
                         "correct_abstentions": 0})
    failures, results, safety_violations, schema_violations = [], [], [], []
    protected_count = 0
    for case in cases:
        expected = case["expected"]
        output = analyzer(case["text"], case["source"], case.get("published", ""),
                          title=case.get("title", ""))
        if not isinstance(output, dict):
            raise ValueError("Analyzer returned non-object for " + case["id"])
        disease = output.get("disease")
        location = output.get("location")
        actual = {"event_status": output.get("event_status"),
                  "triage": output.get("triage"),
                  "is_traveler": output.get("is_traveler"),
                  "disease": disease.get("name") if isinstance(disease, dict) else None,
                  "location_iso": location.get("iso") if isinstance(location, dict) else None}
        schema_errors = []
        if "disease" not in output or (disease is not None and (
                not isinstance(disease, dict) or not isinstance(disease.get("name"), str)
                or not disease.get("name"))):
            schema_errors.append("disease")
        if "location" not in output or (location is not None and (
                not isinstance(location, dict) or not isinstance(location.get("iso"), str)
                or len(location.get("iso", "")) != 2 or not location["iso"].isupper())):
            schema_errors.append("location")
        if actual["event_status"] not in STATUSES:
            schema_errors.append("event_status")
        if actual["triage"] not in {"review", "context"}:
            schema_errors.append("triage")
        if not isinstance(actual["is_traveler"], bool):
            schema_errors.append("is_traveler")
        for field, shape in (("reasons", list), ("evidence", dict),
                             ("location_candidates", list)):
            if not isinstance(output.get(field), shape):
                schema_errors.append(field)
        if schema_errors:
            schema_violations.append({"id": case["id"], "fields": schema_errors})

        mismatches = {}
        for dimension, expected_value in expected.items():
            dimension_totals[dimension] += 1
            if actual.get(dimension) == expected_value:
                dimension_correct[dimension] += 1
            else:
                mismatches[dimension] = {"expected": expected_value,
                                         "actual": actual.get(dimension)}
        want_review = expected["triage"] == "review"
        got_review = actual["triage"] == "review"
        confusion[("tp" if got_review else "fn") if want_review
                  else ("fp" if got_review else "tn")] += 1
        protected = expected["event_status"] in PROTECTED_STATUSES
        if protected:
            protected_count += 1
        if protected and (got_review or actual["event_status"] == "active"):
            safety_violations.append(case["id"])

        want_geo, got_geo = expected["location_iso"], actual["location_iso"]
        geography["locatable"] += want_geo is not None
        geography["abstention_required"] += want_geo is None
        geography["assigned"] += got_geo is not None
        geography["abstained"] += got_geo is None
        geography["abstained_locatable"] += got_geo is None and want_geo is not None
        geography["correct_assignments"] += got_geo is not None and got_geo == want_geo
        geography["correct_abstentions"] += got_geo is None and want_geo is None
        row = {"id": case["id"], "category": case["category"],
               "actual": actual, "expected": expected, "mismatches": mismatches}
        results.append(row)
        if mismatches:
            failures.append({**row, "rationale": case["rationale"]})

    metrics = {
        "review": {**confusion,
                   "precision": fraction(confusion["tp"], confusion["tp"] + confusion["fp"]),
                   "recall": fraction(confusion["tp"], confusion["tp"] + confusion["fn"])},
        "geography": {**geography,
                      "precision": fraction(geography["correct_assignments"], geography["assigned"]),
                      "recall": fraction(geography["correct_assignments"], geography["locatable"]),
                      "required_abstention_accuracy": fraction(
                          geography["correct_abstentions"], geography["abstention_required"])},
        "dimensions": {key: fraction(dimension_correct[key], total)
                       for key, total in sorted(dimension_totals.items())},
        "protected_cases": protected_count,
    }
    gates = {
        "valid_output_contract": not schema_violations,
        "no_context_negation_or_resolution_promoted": not safety_violations,
        "review_precision_at_least_95pct": _meets(metrics["review"]["precision"], .95),
        "review_recall_at_least_90pct": _meets(metrics["review"]["recall"], .90),
        "country_precision_at_least_95pct": _meets(metrics["geography"]["precision"], .95),
        "country_recall_at_least_90pct": _meets(metrics["geography"]["recall"], .90),
        "required_geographic_abstention_100pct": _meets(
            metrics["geography"]["required_abstention_accuracy"], 1.0),
    }
    return {"kind": "synthetic_regression_results", "case_count": len(cases),
            "metrics": metrics, "gates": gates, "passed": all(gates.values()),
            "safety_violations": safety_violations, "schema_violations": schema_violations,
            "failures": failures, "results": results}


def _meets(metric, threshold):
    return metric["value"] is not None and metric["value"] >= threshold


def render_report(report):
    def show(metric):
        score = "undefined" if metric["value"] is None else f'{100 * metric["value"]:.1f}%'
        return f'{score} ({metric["numerator"]}/{metric["denominator"]})'

    metrics = report["metrics"]
    lines = [f'Synthetic regression only: {report["case_count"]} authored examples.',
             "Not independent epidemiological validation or a real-world performance estimate.",
             f'Review precision: {show(metrics["review"]["precision"])}',
             f'Review recall: {show(metrics["review"]["recall"])}',
             f'Country precision among assignments: {show(metrics["geography"]["precision"])}',
             f'Country recall among locatable cases: {show(metrics["geography"]["recall"])}',
             f'Required geographic abstention: {show(metrics["geography"]["required_abstention_accuracy"])}',
             f'Geographic abstentions: {metrics["geography"]["abstained"]}; '
             f'{metrics["geography"]["abstained_locatable"]} were locatable.',
             f'Unsafe promotions: {len(report["safety_violations"])}/{metrics["protected_cases"]} protected cases.']
    lines.extend(f'{dimension}: {show(metric)}' for dimension, metric in metrics["dimensions"].items())
    lines.append("Gates: " + ("PASS" if report["passed"] else "FAIL"))
    lines.extend("  FAIL " + name for name, passed in report["gates"].items() if not passed)
    for failure in report["failures"]:
        lines.append(f'  {failure["id"]}: ' + "; ".join(
            f'{dimension}: expected {values["expected"]!r}, got {values["actual"]!r}'
            for dimension, values in failure["mismatches"].items()))
    for violation in report["schema_violations"]:
        lines.append(f'  {violation["id"]}: invalid contract fields {violation["fields"]}')
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--json", action="store_true", help="Print complete results as JSON")
    parser.add_argument("--check", action="store_true", help="Exit nonzero when a release gate fails")
    args = parser.parse_args(argv)
    from signal_quality import analyze_text
    corpus = load_corpus(args.corpus)
    report = evaluate_cases(corpus["cases"], analyze_text)
    report["corpus_version"] = corpus["version"]
    report["labeling"] = corpus["labeling"]
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render_report(report))
    return 1 if args.check and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
