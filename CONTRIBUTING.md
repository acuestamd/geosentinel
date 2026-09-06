# Contributing

Thanks for looking. This is a solo-maintained open-source project, so response times vary.

## What I'm especially looking for

- **Corrections from people with actual epi-surveillance background.** If a signal is misleading, a confidence score is wrong, or the framing of something in the README implies more than it should, please tell me. I'd rather be embarrassed in an issue than wrong in the dashboard.
- **New data sources** that publish reliable, free, public feeds. ProMED's RSS broke in 2026 — I'm watching for it to come back, and any other authoritative free source is welcome.
- **Geocoder improvements.** It's currently a keyword list with word-boundary matching for short keys. Better: an actual NER pass or a real gazetteer.
- **Cross-source corroboration tiers.** The UI distinguishes source provenance, while every extraction remains unverified. Independent corroboration needs document-origin tracking and an evaluation protocol.

## What I'll probably decline

- Anything that requires paid APIs or non-stdlib Python dependencies. The "runs free on GitHub Actions, no infrastructure" property is intentional.
- Features that would make the dashboard easier to mistake for an authoritative or clinical source. The non-diagnostic, non-authoritative framing is load-bearing.
- Aggressive scraping of sources that don't want it (ToS matters; see issue #1 for context).

## Reporting issues

Bug reports, geocoder false positives, suggested new sources, and "this signal looks wrong because…" are all useful. A link to the affected signal URL or a screenshot helps a lot.

For potential security issues, see [SECURITY.md](SECURITY.md).

## Pull requests

PRs welcome. For anything beyond a typo or small fix, please open an issue first so we can check scope alignment. The project is intentionally narrow — an open early-warning *signal layer*, not a production surveillance system.

When in doubt: I'd rather merge something honest about its limitations than something polished that overpromises.
