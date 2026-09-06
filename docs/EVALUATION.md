# Evaluation and its limits

The [dengue pilot](DENGUE_PILOT.md) has a separate temporal forecasting evaluation based on an aggregated weekly case series. Its model comparison is unrelated to the synthetic text-extraction scores below. Historical inputs are the provider's latest revised data; results must be labeled retrospective rather than operational or prospective. The first ready forecast issued each UTC week is archived from deployment onward, allowing future scoring against subsequent notifications. These newly archived records do not supply historical vintages retroactively.

The included corpus is **60 synthetic examples written and labeled by an AI coding assistant**. It is a development regression suite, not real outbreak data, an independent review, or an estimate of epidemiological performance. Passing it does not establish operational readiness, WHO quality, endorsement, real-world sensitivity, or an ability to forecast spread.

Each label has a written rationale based on what the text asserts. The corpus includes initial cases and adversarial cases added during development. The software can be improved against these examples, so they are a training/development set; they must never be presented as a held-out test set. They have fixed publication dates and make no assertion that the named events occurred. They must not be ingested into the public dashboard.

## Reproduce the development check

Python's standard library is sufficient; no network or account credentials are used.

```sh
python -m unittest -v test_evaluation
python evaluate.py --check
python evaluate.py --json > evaluation-results.json
```

`fixtures/triage_cases.json` contains the input, source type, expected labels, and rationale. `evaluate.py` calls the same `signal_quality.analyze_text` function used by the scanner. It prints every disagreement by dimension and retains per-case results in its JSON report. The tests also verify that missing predictions and wrong assignments remain in the metric denominators.

The corpus covers current event language, outbreak-end declarations, negation, historical discussion, research, preparedness, vaccine activities, multievent roundups, disease names that contain place names, country name collisions, URL contamination, first-person traveler illness, conditional travel advice, and missing or ambiguous geography. A small number of French and Spanish examples check specific rules; these do not establish multilingual coverage.

## Label contract

- `event_status` describes what the supplied text asserts: `active`, `resolved`, `negated`, `context`, or `uncertain`. `active` does not mean independently confirmed, currently transmissible, or still ongoing at the time a reader views the dashboard.
- `triage=review` means the item merits a human look. A disease-country WHO DON title can be reviewable with an uncertain event status. Explicit event language without attributable geography stays in context in this implementation.
- `disease` is the canonical named disease, or null when no disease is stated. The multievent roundup omits this label because there is no single correct disease to choose.
- `location_iso` is the uniquely attributable country. A null label explicitly requires abstention. The country named inside a disease, URL, or ambiguous multievent statement is not a defensible point on a map.
- `is_traveler` requires a report of travel-associated illness. A travel guide or conditional recommendation is not a traveler case. This flag does not establish where an infection was acquired.

Every case has a country-or-abstention label. The geography metrics measure **country attribution only**. They do not validate city choice, coordinates, district boundaries, exposure location, or a map marker's apparent precision.

## Metrics and regression gates

Every rate includes its numerator and denominator. A zero denominator is reported as undefined and fails a gate requiring that metric; it is never converted into a perfect score.

| Metric | Numerator | Denominator |
| --- | --- | --- |
| Review precision | Correctly retained review items | All predicted review items |
| Review recall | Correctly retained review items | All labeled review items |
| Country precision | Correct country assignments | All non-null country assignments, including invented countries on abstention cases |
| Country recall | Correct country assignments | All cases labeled with a known country, including cases where the model abstains |
| Required abstention accuracy | Correct null country outputs | All cases requiring geographic abstention |
| Exact dimension agreement | Correct predictions for that dimension | All examples carrying a label for that dimension |

The report separately counts all geographic abstentions, abstentions on locatable cases, and protected examples incorrectly promoted to active or review. This prevents a system from appearing accurate merely by suppressing difficult cases.

`--check` enforces development gates: no resolved, negated, or context example promoted to active or review; a valid output contract; at least 95% review precision and country precision; at least 90% review recall and country recall; and 100% required geographic abstention. The regression tests additionally require each stored label to pass. These are engineering thresholds selected for this small, deliberately constructed suite, not clinical acceptance criteria. Do not lower a threshold or relabel a case merely to make a failing implementation pass; correct errors or document and independently review a change to the labeling policy.

## Required next step: a blinded, real-data evaluation

An epidemiologist should define the intended use, acceptable missed-event burden, and false-positive workload before the system is considered for an operational setting. A future study should follow a written protocol:

1. **Freeze scope and sampling.** Specify observation dates, geography, languages, diseases, source families, eligibility rules, and the exact scanner version. Capture consecutive raw feed items, including items the scanner rejects. If sampling is stratified or enriched for rare positives, retain sampling weights and report unweighted stratum results; an enriched sample's precision is not routine operational PPV.
2. **Preserve an audit trail.** Record retrieval time in UTC, original publication and update times, source URL, canonical URL, permitted text or archived evidence, feed/query identity, and collection failures. Keep timestamps distinct. Remove personal identifiers from social material unless they are necessary and permitted for the study. Resolve lawful retention and redistribution before publishing a dataset.
3. **Blind annotation.** Have at least two trained reviewers, including an epidemiologist, label the original text without model output, predicted score, queue position, or another reviewer's labels. Use a written rubric and a pilot exercise to resolve confusing terms before the held-out evaluation. Mark insufficient evidence explicitly; do not force uncertain cases into positive or negative truth. Independently adjudicate disagreements and report their frequency.
4. **Separate text truth from event truth.** Label whether the text reports a relevant event and whether the event is subsequently corroborated by authoritative records as separate outcomes. A correct extraction from an inaccurate report is an extraction success and can still be an event-level false positive. Record review-worthy status, disease, event status, geography and its supported precision, travel/exposure attribution, evidence passages, and uncertainty.
5. **Control leakage and duplicates.** Split by event and time, keeping updates, syndication, reposts, and near duplicates together. Keep the final test period hidden from rule development. Evaluate raw items and deduplicated event clusters separately; a hundred copies of one report are not a hundred independent successes.
6. **Measure detection and workload.** Report PPV and recall against the stated reference standard, confusion counts, uncertainty exclusions, abstention rates, false alarms per analyst-day, review time, and confidence intervals. Provide results by source family, language, geography, disease group, and official versus community content. Choose sample size from the precision needed for these estimates and the expected event rate, with statistical input.
7. **Measure location faithfully.** Evaluate country, administrative area, and city only where each is supported by the source. Include false localization, ambiguous cross-border attribution, and abstentions in the denominators. A country's representative map point must not be scored as an observed case coordinate.
8. **Measure timeliness with observable clocks.** Distinguish first accessible source publication, first system ingestion, analyst disposition, and first authoritative notice. Report ingestion delay as ingestion minus source publication, and lead/lag relative to the authoritative notice with a stated sign convention. Audit time zones and updated timestamps. A later news story describing an earlier outbreak does not demonstrate earlier detection. Report missing dates and intervals separately.
9. **Measure source coverage and outages.** Count eligible documents available, successfully retrieved, processed, rejected, and retained per source and time window. Record rate limits, credential failures, parser failures, disabled feeds, and language restrictions. Compare detected events with a defined external reference set. Raw signal counts do not establish population coverage; no finite feed inventory reveals every true outbreak.
10. **Publish a versioned result and monitor drift.** Release the protocol, labeling rubric, aggregate counts and intervals, error examples with appropriate permissions, scanner commit, and reproducible evaluation code. Set operational acceptance criteria with epidemiologists before opening the held-out results. Repeat the evaluation after material rule or source changes, and monitor real review workload and missed events over time.

Until that work is complete, public claims should describe this tool as an experimental, independently operated system for organizing open-source signals for human review.
