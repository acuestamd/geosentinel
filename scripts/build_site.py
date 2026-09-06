"""Build an allowlisted static artifact; never publish runner caches or sources."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from signal_store import validate_output
from dengue_forecast import validate_payload


def build(destination=None):
    destination = Path(destination or ROOT / "_site")
    data = json.loads((ROOT / "signals.json").read_text())
    validate_output(data)
    if data["health"]["status"] == "unavailable":
        raise ValueError("Refusing to publish an unavailable scan")
    dengue = json.loads((ROOT / "dengue_forecast.json").read_text())
    validate_payload(dengue)
    # Validate every dataset before replacing a previously usable artifact.
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    manifest = {"schema_version": data["schema_version"], "lastScan": data["lastScan"], "files": {}}
    for name in ("index.html", "dashboard.js", "dengue-pilot.js", "signals.json", "dengue_forecast.json", "LICENSE"):
        payload = (ROOT / name).read_bytes()
        (destination / name).write_bytes(payload)
        manifest["files"][name] = hashlib.sha256(payload).hexdigest()
    (destination / ".nojekyll").touch()
    manifest["revision"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    manifest["dengue"] = {"status": dengue["status"], "generated_at": dengue["generated_at"]}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Built {destination}: {len(data['signals'])} documents; {data['health']['status']} coverage")
    return manifest


if __name__ == "__main__":
    build()
