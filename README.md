# 🌐 GeoSentinel 2.0

**An open, self-running OSINT layer for disease-outbreak early warning.**

GeoSentinel 2.0 aggregates five public sources — the WHO Disease Outbreak News API, PAHO news, GDELT global news, Mastodon, and Reddit — into a single live map of emerging disease signals. It runs itself every 30 minutes on GitHub Actions, costs nothing to operate, and is built entirely on the Python standard library with zero infrastructure. The goal is a fast, transparent, fully reproducible **early-warning layer** that flags signals worth a closer look from validated epidemiological systems.

🔗 **Live dashboard:** https://acuestamd.github.io/project-geosentinel/

<img src="https://img.shields.io/badge/status-live-brightgreen" alt="Live"> <img src="https://github.com/acuestamd/project-geosentinel/actions/workflows/test.yml/badge.svg" alt="Tests"> <img src="https://img.shields.io/badge/sources-5-blue" alt="Sources"> <img src="https://img.shields.io/badge/updates-every%2030%20min-orange" alt="Updates"> <img src="https://img.shields.io/badge/infra%20cost-%240-success" alt="Zero infra cost"> <img src="https://img.shields.io/badge/license-MIT-lightgrey" alt="MIT">

> ℹ️ **Scope:** GeoSentinel 2.0 is **decision-support, not a decision-maker.** It surfaces early, often-unverified open-source signals to help a trained reader decide what to look at next. It is **not** a diagnostic device and **not** a substitute for validated surveillance, clinical judgment, or official public-health guidance. Do not make clinical, operational, or travel decisions from it alone. See [Honest scope & limitations](#-honest-scope--limitations).

## 🛰️ Data sources

| Source | Type | Coverage |
|--------|------|----------|
| 🏥 **WHO** | Disease Outbreak News API | Official alerts, global |
| 🌎 **PAHO** | News RSS (WHO Americas region) | Regional health news, Americas |
| 📰 **GDELT** | Global news (CDC, Reuters, AFP, Al Jazeera...) | Breaking outbreaks |
| 🐘 **Mastodon** | Public hashtag timelines | Symptom reports, early signals |
| 💬 **Reddit** | Community reports (OAuth, app-only) | Travel health experiences |

Every signal carries a `source` badge, so its provenance is visible at a glance — an official WHO alert is never silently mixed in with an anonymous post.

## 🔬 Features

- **Self-running** — refreshes automatically every 30 minutes via GitHub Actions, no servers to maintain
- **Anomaly detection** — historical baseline comparison flags unusual spikes
- **Traveler signal detection** — NLP patterns identify "came back sick from..." reports
- **Flight-path modeling** — maps potential spread via IATA air-route hubs
- **Case/death count extraction** — conservative regex pulls counts from source text when present
- **Free-text search** — substring match across disease, location, and summary
- **Interactive map** — Leaflet-based, with severity-coded markers
- **Source-filtered views** — isolate WHO, PAHO, news, Mastodon, or Reddit
- **Provenance-first & reproducible** — stdlib-only, MIT-licensed, every step auditable in one file

## 🏗️ Architecture

```
GitHub Actions (cron, every 30 min)
    → scanner_v2.py (Python stdlib only)
        → WHO + PAHO + GDELT + Mastodon + Reddit OAuth
        → NLP disease detection + geocoding + anomaly scoring
        → case/death count extraction (regex)
        → signals.json (generated in-runner)
    → GitHub Pages (deployed from the same job's artifact)
        → index.html (Leaflet map + dashboard)
```

**Zero infrastructure cost.** Runs entirely on GitHub Actions + Pages.

## 📊 Signal-processing pipeline

1. **Collection** — sequential queries across five source APIs
2. **Disease detection** — word-boundary regex against ~65 disease patterns
3. **Geocoding** — ~130 city/country database; resolves each signal to the location named *first* in the text (the headline's subject, not a country mentioned in passing), preferring city over country, with word-boundary matching for short keys
4. **Severity scoring** — base disease severity + modifiers (deaths, outbreak scale, traveler)
5. **Case/death extraction** — conservative regex with sanity caps (handles "N cases", "N,NNN", and "N million/thousand")
6. **Anomaly detection** — per-scan report-volume baseline (EWMA); flags a surge past a Poisson band, and separately flags first-seen (country, disease) pairs as *new*
7. **Deduplication** — hash-based + location clustering
8. **Flight risk** — IATA hub mapping for affected countries

## 🔎 Honest scope & limitations

Transparency about what this does and doesn't do is a design goal, not a footnote. Known limitations, stated plainly:

- **Single-source signals are unverified.** A Reddit post about feeling sick is not an outbreak. The confidence score reflects source reliability, not signal truth — corroboration is the reader's job.
- **Coverage is English-skewed.** An outbreak with no English-language news has low signal density here for days. Absence of signal ≠ absence of outbreak. (Broader multilingual coverage is the top item on the roadmap.)
- **Geocoding is keyword-based.** It resolves to the location named first in the headline, which handles passing mentions of other countries — but it can still misplace a signal when the first location named isn't the outbreak's, and it only knows the ~130 places in its database.
- **Case/death extraction is regex-only.** "N cases" works; "dozens affected" doesn't. Most WHO DON titles carry no numbers.
- **No cross-source corroboration tiers yet.** A single post and a WHO DON alert are distinguished only by the `source` badge today; weighted corroboration is on the roadmap.
- **It publishes; it does not notify.** Operational surveillance systems coordinate with the relevant Ministry of Health. This one publishes to GitHub Pages — it is an open signal layer, not an alerting authority.
- **It depends on third-party feeds.** Any upstream source can change format or rate-limit without notice.

For validated, operational surveillance, use [WHO EIOS](https://www.who.int/initiatives/eios), [HealthMap](https://healthmap.org/), [ProMED](https://promedmail.org/), and the clinic-based [GeoSentinel](https://www.istm.org/geosentinel) network. GeoSentinel 2.0 is a fast, open *complement* to those — useful for flagging signals that warrant a closer look — not a replacement.

## ⚙️ Configuration

For Reddit signals, register a "script" app at <https://www.reddit.com/prefs/apps> and add these under **Settings → Secrets and variables → Actions**:

- `REDDIT_CLIENT_ID`
- `REDDIT_CLIENT_SECRET`

If either is missing, Reddit is skipped silently and the other four sources still run.

## ⚕️ Background & affiliation

The original [GeoSentinel](https://www.istm.org/geosentinel) is the ISTM/CDC travel-medicine surveillance network — ~70 clinics worldwide collecting validated, patient-level data from returning travelers, and the authoritative source for travel-related infectious-disease epidemiology.

**GeoSentinel 2.0** is an independent, open-source OSINT layer inspired by that mission: faster and noisier, built to surface signals that merit a closer look from real epi systems. It is a personal project and is **not** affiliated with or endorsed by WHO, PAHO, ISTM, the GeoSentinel network, or any health authority.

If you work in epidemiologic surveillance and see something here that's wrong or misleading, please open an [issue](https://github.com/acuestamd/project-geosentinel/issues) — that feedback is the most valuable kind. See [CONTRIBUTING.md](CONTRIBUTING.md).

## 📜 License

[MIT](LICENSE). Use freely; attribution appreciated. No warranty — see LICENSE for the full disclaimer of liability.
