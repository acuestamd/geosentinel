"""Preserve the first ready forecast each UTC week for prospective evaluation.

Writes one new, size-bounded public aggregate record after deployment on main.
An existing weekly record is never overwritten. No source account data or
credentials are included; this archive starts now and is not historical evidence.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dengue_forecast import validate_payload

MAX_RECORD_BYTES = 600_000


def make_record(payload, revision):
    validate_payload(payload)
    if payload["status"] != "ready" or not payload.get("forecasts"):
        return None
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("A full code revision is required for the forecast archive")
    # These are published, aggregate municipal series, never individual records.
    history_keys = ("week", "cases", "temperature_min", "humidity_max")
    forecast_keys = ("week", "horizon_weeks", "data_horizon_weeks", "point", "lower", "upper", "model")
    record = {
        "schema_version": 1,
        "issued_at": payload["generated_at"],
        "code_revision": revision,
        "model_version": payload.get("model_version"),
        "location": {key: payload["location"].get(key) for key in ("name", "country", "geocode")},
        "source": {key: payload["source"].get(key) for key in ("name", "url", "retrieved_at", "raw_sha256")},
        "forecasts": [{key: row.get(key) for key in forecast_keys} for row in payload["forecasts"]],
        "input_history": [{key: row.get(key) for key in history_keys} for row in payload["history"]],
        "assessment": "Experimental forecasts frozen at issuance. Outcomes and prospective accuracy are not yet assessed.",
        "target": "Weekly notified dengue cases in Rio de Janeiro; source reports may be revised later.",
    }
    record["published_payload_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()
    if len(json.dumps(record, allow_nan=False).encode()) > MAX_RECORD_BYTES:
        raise ValueError("Forecast archive record exceeds its size limit")
    return record


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_REF") != "refs/heads/main":
        print("Forecast archive writes run only on main in GitHub Actions.")
        return
    payload = json.loads((ROOT / "dengue_forecast.json").read_text())
    record = make_record(payload, os.environ.get("GITHUB_SHA", ""))
    if record is None:
        print("No ready dengue forecast to archive.")
        return
    issued = datetime.fromisoformat(record["issued_at"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    if issued.tzinfo is None or not -300 <= (now - issued).total_seconds() <= 172800:
        raise ValueError("Archive requires a recently issued UTC-aware forecast")
    week = issued.astimezone(timezone.utc).strftime("%G-W%V")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Invalid repository identifier")
    url = f"https://api.github.com/repos/{repo}/contents/reports/dengue/{week}.json"
    headers = {"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
               "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "GeoSentinel weekly dengue archive"}
    try:
        with urllib.request.urlopen(urllib.request.Request(url + "?ref=main", headers=headers), timeout=20) as response:
            response.read(1)
        print("This week's first dengue forecast is already preserved.")
        return
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    encoded = json.dumps(record, indent=2, allow_nan=False) + "\n"
    body = {"message": f"Preserve experimental dengue forecast for {week}", "branch": "main",
            "content": base64.b64encode(encoded.encode()).decode()}
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="PUT")
    with urllib.request.urlopen(request, timeout=20) as response:
        response.read(1024)
    print("First weekly dengue forecast preserved for future assessment.")


if __name__ == "__main__":
    main()
