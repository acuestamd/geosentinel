"""Document identity, retention, timestamps and publishable schema checks."""
import hashlib
import json
import re
import urllib.parse
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

SCHEMA_VERSION = "3.0"
RETENTION_DAYS = 30


def parse_date(value):
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        value = str(value).strip()
        if re.fullmatch(r"\d{8}T\d{6}Z", value):
            return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            result = parsedate_to_datetime(value)
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def normalize_date(value):
    date = parse_date(value)
    return date.isoformat() if date else ""


def canonical_url(value):
    try:
        url = urllib.parse.urlsplit(str(value or "").strip())
        if url.scheme.lower() not in ("http", "https") or not url.hostname or url.username or url.password:
            return ""
        # Validate ports as well; malformed URLs are retained only as text.
        port = url.port
        host = url.hostname.lower()
        if ":" in host:
            host = "[" + host + "]"
        default_port = 80 if url.scheme.lower() == "http" else 443
        netloc = host + (f":{port}" if port and port != default_port else "")
        query = [(k, v) for k, v in urllib.parse.parse_qsl(url.query, keep_blank_values=True)
                 if not k.lower().startswith("utm_") and k.lower() not in
                 {"fbclid", "gclid", "at_campaign", "at_medium", "mc_cid", "mc_eid"}]
        return urllib.parse.urlunsplit((url.scheme.lower(), netloc, url.path or "/",
                                       urllib.parse.urlencode(sorted(query)), ""))
    except (ValueError, TypeError):
        return ""


def document_id(url, text="", published="", source=""):
    normalized = re.sub(r"\s+", " ", text).strip()
    identity = canonical_url(url) or f"{source}|{normalized}|{published}"
    return hashlib.sha256(identity.encode()).hexdigest()[:24]


def deduplicate_documents(signals):
    """Deduplicate documents, never suppress distinct city/date/source reports."""
    seen = {}
    rank = {"official": 3, "media": 2, "community": 1}
    for signal in signals:
        identity = signal.get("document_id") or document_id(
            signal.get("url"), signal.get("original_title") or signal.get("summary", ""),
            signal.get("published", ""), signal.get("source", ""))
        current = {**signal, "id": identity, "document_id": identity}
        current["observed_via"] = sorted(set(current.get("observed_via", []) + [current.get("source", "unknown")]))
        current["queries"] = sorted(set(current.get("queries", [])))
        previous = seen.get(identity)
        if previous:
            dates = [x for x in (previous.get("first_seen"), current.get("first_seen")) if x]
            last = [x for x in (previous.get("last_seen"), current.get("last_seen")) if x]
            # Prefer the original official publisher if a social feed links to it.
            if rank.get(previous.get("evidence_level"), 0) > rank.get(current.get("evidence_level"), 0):
                chosen = dict(previous)
            else:
                chosen = current
            chosen["observed_via"] = sorted(set(previous["observed_via"] + current["observed_via"]))
            chosen["queries"] = sorted(set(previous["queries"] + current["queries"]))
            if dates:
                chosen["first_seen"] = min(dates)
            if last:
                chosen["last_seen"] = max(last)
            seen[identity] = chosen
        else:
            seen[identity] = current
    return list(seen.values())


def merge_retained(previous, fresh, now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=RETENTION_DAYS)
    current_ids = {s["document_id"] for s in fresh}
    old = [{**s, "is_carried_forward": True} for s in previous]
    new = [{**s, "is_carried_forward": False} for s in fresh]
    out = []
    for signal in deduplicate_documents(old + new):
        date = parse_date(signal.get("published")) or parse_date(signal.get("first_seen"))
        if date and cutoff <= date <= now + timedelta(minutes=5):
            signal["is_carried_forward"] = signal["document_id"] not in current_ids
            out.append(signal)
    return sorted(out, key=lambda s: (s.get("published") or s.get("first_seen") or "", s["document_id"]), reverse=True)


def load_document_cache(path):
    try:
        with open(path) as handle:
            data = json.load(handle)
        if data.get("schema_version") == SCHEMA_VERSION and isinstance(data.get("signals"), list):
            # Reject a corrupt cache rather than propagate bad records.
            validate_signals(data["signals"])
            if not isinstance(data.get("source_health", {}), dict):
                data["source_health"] = {}
            else:
                data["source_health"] = {key: row for key, row in data.get("source_health", {}).items()
                                         if isinstance(row, dict)}
            return data
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        pass
    return {"schema_version": SCHEMA_VERSION, "signals": [], "source_health": {}}


def validate_signals(signals):
    ids = set()
    for row in signals:
        if not isinstance(row, dict):
            raise ValueError("Signal must be an object")
        identity = row.get("document_id")
        if not isinstance(identity, str) or not identity or identity in ids:
            raise ValueError("Document identifiers must be present and unique")
        ids.add(identity)
        if row.get("triage") not in ("review", "context"):
            raise ValueError("Invalid triage disposition")
        if row.get("event_status") not in ("active", "resolved", "negated", "context", "uncertain"):
            raise ValueError("Invalid event status")
        if row.get("verification_status") != "unverified":
            raise ValueError("Automated collection cannot verify events")
        if row.get("event_status") in ("resolved", "negated", "context") and row.get("triage") == "review":
            raise ValueError("Context or resolved reports cannot enter active review queue")
        location = row.get("location")
        if location is not None:
            if not isinstance(location, dict) or not isinstance(location.get("iso"), str):
                raise ValueError("Invalid location")
            lat, lng = location.get("lat"), location.get("lng")
            if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)) or not -90 <= lat <= 90 or not -180 <= lng <= 180:
                raise ValueError("Invalid coordinates")
        for key in ("summary", "source", "original_title", "published", "retrieved_at"):
            if not isinstance(row.get(key), str):
                raise ValueError(f"Invalid {key}")
        if row["published"] and not parse_date(row["published"]):
            raise ValueError("Invalid publication date")
        if not isinstance(row.get("rationale"), list):
            raise ValueError("Missing auditable rationale")


def validate_output(data):
    if data.get("schema_version") != SCHEMA_VERSION or not parse_date(data.get("lastScan")):
        raise ValueError("Invalid output schema or scan timestamp")
    validate_signals(data["signals"])
    if data.get("health", {}).get("status") not in ("healthy", "degraded", "unavailable"):
        raise ValueError("Invalid source health")
    return True
