# Methodology and interpretation

Version 3.0 · independent prototype · automated records remain unverified.

## Intended use

A trained reader can discover a public report, examine its source, see automated extraction and triage reasons, and decide what merits investigation. GeoSentinel does not verify a disease event, issue a public-health alert, establish clinical severity or recommend interventions.

The workflow is informed by the separation of detection, verification and assessment described by [WHO](https://www.who.int/activities/rapidly-detecting-and-responding-to-health-emergencies) and the [EIOS initiative](https://www.who.int/initiatives/eios/eios-technology). This is a design reference, not certification or evidence of equivalence. Operational verification involves authorities, expertise and processes outside this application.

## From feed item to reviewable document

1. **Collect:** fixed public feed endpoints, bounded response size, request timeouts and limited retries. HTTP 429 stops further requests to that host in the scan. Feed schema problems and optional missing configuration are recorded.
2. **Normalize:** preserve inline text, decode HTML entities and retain original source URLs. Publication date is never fabricated from retrieval time. `date_basis=gdelt_index` distinguishes GDELT index time from a publisher-supplied publication date.
3. **Interpret assertions:** disease and location matching is performed on relevant text passages. URLs, embedded country words in disease names, historical references, negation, end-of-outbreak announcements and agency attribution receive explicit rules. Selected event text and reasons are included in each record.
4. **Abstain:** multiple unresolved events, incidental geography or missing local evidence can lead to context classification and/or no map location. A source report is not forced into one invented outbreak.
5. **Deduplicate documents:** canonical URL identifies a document, with a text/date fallback. Tracking parameters are removed; distinct document paths, cities and dates are not collapsed into a country-level representative. Candidate event IDs group geography/disease for inspection only; they do not establish a single outbreak or independent corroboration.
6. **Retain and validate:** report-date retention is 30 days. Unknown dates use first collection only for retention, not the report-date filter. Retained documents are labeled internally as carried forward. The publishable schema rejects invalid dates, coordinates, duplicate IDs and automatically verified records.

## Interpretation of labels

| Field | Meaning | Does not mean |
| --- | --- | --- |
| Review queue | Automated selection for human inspection | An outbreak is confirmed |
| Context / excluded | Background, resolved, negated or ambiguous material | The source is wrong or the country is safe |
| Possible active event | The text appears to describe a current event | The event has been independently verified |
| Official source | The document was collected from WHO/PAHO | Automated extraction is correct |
| Reported location | A rule matched geography in the source | An exact outbreak location or geographic extent |
| Available feed | The collection endpoint returned usable input | Surveillance coverage is complete |

All records set `verification_status=unverified`. The frontend does not show probability-like confidence scores. Repeated news or posts are not counted as independent confirmation. Case/death counts, when present, come from a selected passage and remain source claims; they are not aggregated into estimated disease incidence.

## Forecasting and mobility

Three different outcomes require different models: future local incidence, international spread, and clinical/public-health severity. Source mentions, weather and flights alone do not identify all three.

The [WHO/TDR EWARS dengue guide](https://www.who.int/publications/i/item/9789240003750) combines epidemiological and alarm indicators with retrospective calibration and evaluation. A locally fitted model and held-out evaluation are required before attaching an outbreak probability to weather conditions. Rainfall, temperature and humidity can be context for vector-borne disease; they do not validate a signal or predict individual disease severity.

The environmental panel uses [Open-Meteo](https://open-meteo.com/en/docs) modeled recent weather and weather forecasts where a sufficiently local coordinate is available. Weather forecasts are not outbreak forecasts. Country centroids are not treated as outbreak-site weather. The panel identifies date windows, unavailable fields and missing calibration rather than inventing a universal risk threshold. Weather data attribution: Open-Meteo, [CC BY 4.0](https://open-meteo.com/en/terms).

Flight-data integration is explicitly **not connected**. The integration should supply dated origin/destination airport pairs, passenger counts or seat-capacity estimates, time window, provenance, licensing and uncertainty. Static airport hubs or historical routes must not be represented as current passenger flows. Additional prerequisites include local incidence, infectious-period assumptions, traveler movement and destination susceptibility. No exportation probability is emitted without these inputs and model validation.

The current deployment supports inspecting environmental drivers and identifying missing inputs. It does not claim validated prediction. The [evaluation protocol](EVALUATION.md) covers prospective and retrospective validation needed for such a model.

## Known limitations

Finite gazetteer; English-biased coverage with selected Spanish/French support; no authoritative incident registry; no shared authenticated analyst decisions; no independent source corroboration; heuristics can both miss and misclassify events; public feed and cache outages; no guarantee of 30-minute scheduling; no calibrated severity, incidence, spread or lead-time estimate. All-source collection failure blocks publication, while partial failures remain visible.

A failure-free software test run cannot remove these limitations. Report errors with the source URL and document ID so the relevant behavior can become a regression test.
