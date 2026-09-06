# GeoSentinel

**An open workspace for reviewing public health signals and their evidence.**

[Open the public dashboard](https://acuestamd.github.io/project-geosentinel/) · [Methodology](docs/METHODOLOGY.md) · [Evaluation](docs/EVALUATION.md) · [Operations](docs/OPERATIONS.md)

GeoSentinel collects public WHO, PAHO, news and community reports, separates possible current events from resolved, negated, historical and ambiguous material, and gives each document a source trail. The map shows reported locations; the evidence ledger helps a reader inspect the original report and the reasons for automated triage.

**All automated records remain unverified.** This is an independent research prototype, not a WHO product, validated surveillance system or clinical decision tool. It is not affiliated with WHO, PAHO, ISTM, CDC or the GeoSentinel clinical surveillance network. Do not make clinical, operational or travel decisions from it alone.

## What version 3 changes

- **Evidence before scores.** Official, media and community provenance are visible. Unsupported confidence percentages, critical-outbreak scores and static flight-risk lines have been removed.
- **Conservative triage.** Negation, resolution, historical research, simulations, current zero-case windows and incidental locations have explicit handling. Ambiguous reports remain available as context. No location is invented when matching is unresolved.
- **Document identity.** Repeated retrieval of the same URL is merged; distinct reports from different cities or dates survive. Sources and collection queries remain traceable.
- **Honest freshness.** Collection time, source date and missing dates stay distinct. GDELT index timestamps are labeled as such. A 30-day document cache survives partial feed outages, subject to GitHub cache availability.
- **Consistent exploration.** Search, source, report-date and review-scope filters affect the ledger, map, counts and analysis together. Export the filtered evidence as JSON.
- **Visible source health.** The dashboard distinguishes available, partial, failed and unconfigured feeds, and warns when collection is overdue or refresh fails.
- **Environmental context.** Recent and forecast weather can support local investigation for relevant pathogens. No outbreak probability or clinical-severity prediction is produced; current flight/passenger data are not connected.
- **Publication gates.** Regression tests, a labeled synthetic evaluation corpus, frontend checks and output validation run before deployment. An allowlist limits the public artifact to the dashboard, dataset, license and integrity manifest.

## Sources

| Feed | What it provides | Important limitation |
| --- | --- | --- |
| WHO Disease Outbreak News | Official outbreak publications | May lag the initial event; extraction still needs review |
| PAHO news RSS | Official regional publications | Includes policy and prevention material |
| GDELT DOC | News discovery | Rate limits and index-date semantics; no guarantee of coverage |
| Mastodon public hashtags | Community and reposted information | Unverified; repeated and automated accounts can dominate |
| Reddit OAuth | Public community posts | Optional; disabled until credentials are configured |

The UI reports actual collection status. A list of supported feeds is not a claim that all are working. No signal does **not** mean no outbreak.

## Architecture

```text
GitHub Actions (target: every 30 minutes)
  collectors.py       bounded requests, timeouts, source-health records
  signal_quality.py   inspectable text triage and geographic abstention
  scanner_v2.py       normalized documents and evidence metadata
  signal_store.py     document identity, 30-day retention, schema checks
  context_signals.py  optional local weather and explicit forecasting gaps
  scripts/build_site.py
    -> index.html + dashboard.js + signals.json + manifest.json
    -> GitHub Pages
```

Python uses the standard library. The frontend uses Leaflet and OpenStreetMap with visible attribution. GitHub Actions scheduling and public feeds are best-effort services, not an availability SLA.

## Run locally

Python 3.11 and Node 22 are used in CI. No Python or Node package installation is required.

```sh
python3 -m unittest discover -v
python3 evaluate.py --check
node --test test_dashboard.cjs
python3 scanner_v2.py
python3 scripts/build_site.py
python3 -m http.server 8000 --directory _site --bind 127.0.0.1
```

The scanner accesses public feeds. All-source failure preserves the previously published site and fails the run. Optional weather requests may fail independently, without making missing weather look normal or safe.

For Reddit, configure `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` in repository Actions secrets. Never commit credentials. No flight-data provider is configured; see the [forecasting roadmap and data contract](docs/METHODOLOGY.md#forecasting-and-mobility).

## Quality and limits

The synthetic corpus is a **development regression suite**, not an independent estimate of sensitivity, predictive value or lead time. It contains explicit positive and adversarial examples and is known to the implementer. Passing it does not establish real-world epidemiological performance. The [evaluation protocol](docs/EVALUATION.md) specifies how to build an independently labeled real-world validation set.

Rules currently favor English with selected Spanish/French aliases and phrasing. Geographic coverage is finite, mixed-event articles can be withheld, and incorrectly labeled reports will still occur. The static site has no shared analyst adjudication, authenticated review or verified-alert publishing workflow.

## Contribute

Useful contributions include false-positive/false-negative examples, feed-format fixtures, independently reviewed geography, multilingual evaluation and surveillance validation. See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

Code is MIT licensed. Source publications and map/weather data retain their respective licenses and attribution requirements.
