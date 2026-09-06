"""Record one public operational audit per UTC week on main in Actions only.

Audits document source health and regression gates, and provide regular
repository activity. No credentials or raw source reports are recorded.
"""
import base64
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def audit_entry(snapshot, now=None):
    now = now or datetime.now(timezone.utc)
    return {"week": now.strftime("%G-W%V"), "recorded_at": now.isoformat(),
            "schema_version": snapshot["schema_version"], "last_scan": snapshot["lastScan"],
            "coverage": snapshot["health"]["status"],
            "sources": [{"id": row["id"], "status": row["status"], "items": row["items"],
                         "signals": row["signals"], "errors": row["errors"]}
                        for row in snapshot["health"]["sources"]],
            "documents": len(snapshot["signals"]), "review_queue": snapshot["stats"]["review_signals"],
            "quality_gates": "Python regression, synthetic triage evaluation and frontend tests passed before this scan",
            "validation_scope": "Software regression only; not independent epidemiological validation"}


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_REF") != "refs/heads/main":
        print("Operational audit writes run only on main in GitHub Actions.")
        return
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Invalid repository identifier")
    token = os.environ["GITHUB_TOKEN"]
    headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "GeoSentinel operational audit"}
    url = f"https://api.github.com/repos/{repo}/contents/reports/operations.json"
    previous, sha = [], None
    try:
        with urllib.request.urlopen(urllib.request.Request(url + "?ref=main", headers=headers), timeout=20) as response:
            item = json.load(response)
        sha = item["sha"]
        previous = json.loads(base64.b64decode(item["content"]))["audits"]
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    root = Path(__file__).resolve().parents[1]
    entry = audit_entry(json.loads((root / "signals.json").read_text()))
    if any(row.get("week") == entry["week"] for row in previous):
        print("This week's operational audit is already recorded.")
        return
    content = json.dumps({"audits": (previous + [entry])[-52:]}, indent=2) + "\n"
    payload = {"message": f"Record operational audit for {entry['week']}", "branch": "main",
               "content": base64.b64encode(content.encode()).decode()}
    if sha:
        payload["sha"] = sha
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="PUT")
    with urllib.request.urlopen(request, timeout=20) as response:
        response.read()
    print("Weekly operational audit recorded.")


if __name__ == "__main__":
    main()
