# Deployment and operations

## Public site

GitHub Pages publishes the `_site` artifact from the scanner workflow. Supported updates to main trigger a new scan; the schedule targets minutes 7 and 37 of each hour to avoid the busiest hour boundary. GitHub can delay scheduled runs.

Each deployment runs Python regressions, the synthetic evaluation and Node frontend tests before collection. `build_site.py` validates both datasets before replacing the artifact, and allowlists `index.html`, `dashboard.js`, `dengue-pilot.js`, `signals.json`, `dengue_forecast.json`, `LICENSE`, `.nojekyll` and an SHA-256 manifest. Runner caches, source code, environment files and credentials are excluded from the Pages artifact.

The scanner uses short-lived repository permissions for Pages, one operational audit and the first ready dengue forecast archive per UTC week. Third-party actions are pinned to reviewed commit identifiers. Update those pins deliberately and run the same checks.

## Dengue pilot collection and archive

`dengue_forecast.py` requests the public municipal InfoDengue series independently of the global report collector. Its cache `dengue_history_cache.json` is restored and saved with the other runner caches. A valid fresh response is reused for 24 hours; source data gaps, stale observations or provider failure are visible in the pilot. A unavailable pilot does not suppress the global evidence workspace, and unavailable or stale data must not acquire invented predictions.

After deployment, `scripts/record_dengue_forecast.py` preserves the first ready forecast of each UTC week in `reports/dengue/YYYY-Www.json`. Existing weekly records are never replaced. Each record is limited to 600 KB and contains dated predictions, the code revision, source retrieval/hash and an allowlisted aggregate case/climate input series. Credentials, individual records and arbitrary source metadata are excluded. This archive grows by at most one small record per week; it starts at deployment and does not make retrospective forecasts prospective. The public Pages payload can refresh during the week; only the first weekly ready issuance is frozen for evaluation.

Review archive write failures in Actions. Branch rules may prevent these commits even when Pages deploys successfully. Google Trends requires separate access and testing-only conditions; no credentials or Google Cloud project are provisioned by this deployment.

## Feed health and retention

The JSON exposes attempted collection time, last successful collection, source status, received-item counts, emitted-document counts, request failures and last successful response by feed. Optional Reddit credentials are represented as disabled rather than silently omitted. GDELT can rate-limit the shared runner network; the scanner respects the limit and tries again on the next scheduled run.

Documents are cached for 30 days by report date (first-seen date only for undated retention). Cache is best effort: eviction or corruption can remove history. The source feeds may not return the full 30-day window when rebuilding. A total feed outage prevents deployment and preserves the previous public snapshot. The UI flags collection older than two hours and browser refresh failures.

## Preventing silent inactivity

Public GitHub scheduled workflows can be automatically disabled after 60 days without repository activity: [GitHub documentation](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows).

After deployment, `record_operations.py` records one small audit per UTC week in `reports/operations.json`, retaining 52 entries. It documents source health and regression-gate execution and supplies meaningful repository activity. It stores neither raw reports nor secrets. If branch rules or permissions prevent the audit, the workflow fails after deployment so the operational problem is visible; investigate rather than assuming the activity guarantee holds.

To recover a disabled scanner:

```sh
gh workflow enable scan.yml --repo acuestamd/project-geosentinel
gh workflow run scan.yml --repo acuestamd/project-geosentinel --ref main
gh run list --repo acuestamd/project-geosentinel --workflow scan.yml
```

Confirm successful deployment, the public `manifest.json` revision and `signals.json` timestamp, and the dashboard's source-health status. An execution marked successful does not imply complete surveillance or validated event extraction.

## Incident response

- Feed malformed: inspect the source-health error, add a representative fixture, fix parsing and run all gates.
- Partial outage: retained data remain available; missing coverage is visible.
- All-source outage: no new artifact is deployed; the old site will become overdue.
- Bad classifier change: revert the source commit and redeploy. A fingerprint of the processing code invalidates cached classifications when rules change. This rebuild can reduce historical coverage until feeds repopulate it.
- Wrong public report: inspect the source document, record a regression and correct extraction. This static prototype has no operator adjudication database; source status must not be edited to imply official verification.

No paid data or hosting subscription is provisioned. The Open-Meteo free endpoint is used for this personal non-commercial project; a commercial deployment needs an appropriate data plan. External data and tile services have independent availability and usage terms. Growing usage requires reviewing hosting, tile-service and data-provider capacity.
