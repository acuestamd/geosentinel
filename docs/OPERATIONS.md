# Deployment and operations

## Public site

GitHub Pages publishes the `_site` artifact from the scanner workflow. Supported updates to main trigger a new scan; the schedule targets minutes 7 and 37 of each hour to avoid the busiest hour boundary. GitHub can delay scheduled runs.

Each deployment runs Python regressions, the synthetic evaluation and Node frontend tests before collection. `build_site.py` validates the generated data and allowlists `index.html`, `dashboard.js`, `signals.json`, `LICENSE`, `.nojekyll` and an SHA-256 manifest. Runner caches, source code, environment files and credentials are excluded from the Pages artifact.

The scanner uses short-lived repository permissions for Pages and one operational audit per UTC week. Third-party actions are pinned to reviewed commit identifiers. Update those pins deliberately and run the same checks.

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
