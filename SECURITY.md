# Security

This is an open-source project and not intended for production or clinical use. It reads from public APIs and serves a static dashboard via GitHub Pages. There is no user data, no authentication, and no server-side state beyond GitHub Actions runners and Pages artifacts.

## Reporting a vulnerability

If you find a security issue — for example:

- A way to inject content into the rendered dashboard via a crafted signal
- An SSRF or secret-exfiltration vector in the GitHub Actions workflow
- A leaked secret, token, or API key in the repository or git history
- A dependency vulnerability that could be exploited via the scanner

…please open a **private security advisory** at <https://github.com/acuestamd/project-geosentinel/security/advisories/new>.

**Please do not** post exploit details in a public issue or pull request.

## Scope

In scope:
- The scanner script (`scanner_v2.py`)
- The dashboard (`index.html`)
- The GitHub Actions workflow (`.github/workflows/scan.yml`)
- Anything in this repository

Out of scope:
- The accuracy or completeness of upstream sources (WHO, PAHO, GDELT, Mastodon, Reddit)
- Vulnerabilities in third-party libraries (Leaflet, Inter font CDN) — report those to their respective projects

## What this project doesn't do

- It doesn't authenticate users (there are none)
- It doesn't store personal health information
- It doesn't make clinical or travel recommendations
- It doesn't notify any health authority of detected signals
- It doesn't claim to be a substitute for real surveillance systems

If any of the above is somehow happening, that's itself a bug — please report it.

## Response time

Solo-maintained open-source project. Critical issues: aim to acknowledge within a few days. Non-critical: best effort.
