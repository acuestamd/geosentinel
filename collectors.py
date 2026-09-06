"""Bounded public-feed collection with explicit source health (stdlib only)."""
import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

USER_AGENT = "GeoSentinel/3.0 (+https://github.com/acuestamd/project-geosentinel)"
MAX_BYTES = 4 * 1024 * 1024
SOURCES = {"who": "WHO Disease Outbreak News", "paho": "PAHO news",
           "news": "GDELT news", "mastodon": "Mastodon", "reddit": "Reddit"}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class Collector:
    def __init__(self, previous=None, opener=None, sleeper=None):
        self.opener = opener or urllib.request.urlopen
        self.sleep = sleeper or time.sleep
        self.blocked_hosts = set()
        previous = previous if isinstance(previous, dict) else {}
        self.health = {key: {"id": key, "name": name, "status": "pending",
                            "items": 0, "signals": 0, "requests": 0,
                            "successful_requests": 0, "errors": [],
                            "last_success": previous[key].get("last_success") if isinstance(previous.get(key), dict) else None}
                       for key, name in SOURCES.items()}

    def error(self, source, message):
        row = self.health[source]
        if message not in row["errors"] and len(row["errors"]) < 8:
            row["errors"].append(message)
        row["status"] = "partial" if row["successful_requests"] else "error"

    def request(self, source, url, *, headers=None, data=None, xml=False, expected=None):
        row = self.health[source]
        host = urllib.parse.urlsplit(url).hostname
        if host in self.blocked_hosts:
            return None
        req = urllib.request.Request(url, data=data,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})})
        for attempt in range(2):
            row["requests"] += 1
            try:
                with self.opener(req, timeout=15) as response:
                    payload = response.read(MAX_BYTES + 1)
                if len(payload) > MAX_BYTES:
                    raise ValueError("response exceeds 4 MiB limit")
                result = ET.fromstring(payload) if xml else json.loads(payload)
                if expected is not None and not isinstance(result, expected):
                    raise ValueError("unexpected response structure")
                row["successful_requests"] += 1
                row["last_success"] = utc_now()
                row["status"] = "partial" if row["errors"] else "ok"
                return result
            except urllib.error.HTTPError as exc:
                self.error(source, f"HTTP {exc.code}")
                # A rate-limited query stops here; subsequent queries for this
                # source are skipped for this scan, rather than hammering it.
                if exc.code == 429:
                    self.blocked_hosts.add(host)
                    return None
                if exc.code not in (500, 502, 503, 504) or attempt:
                    return None
                self.sleep(2)
            except (ValueError, ET.ParseError):
                self.error(source, "Invalid or oversized feed response")
                return None
            except (OSError, TimeoutError):
                self.error(source, "Connection failed or timed out")
                if attempt:
                    return None
                self.sleep(2)
        return None

    def records(self, source, rows, query=""):
        if not isinstance(rows, list):
            self.error(source, "Missing expected item list")
            return []
        out = []
        for row in rows:
            if not isinstance(row, dict):
                self.error(source, "Malformed feed item skipped")
                continue
            out.append({**row, "source": source, "query": query})
        self.health[source]["items"] += len(out)
        return out

    def who(self):
        url = "https://www.who.int/api/hubs/diseaseoutbreaknews?$orderby=PublicationDate%20desc&$top=50"
        result = self.request("who", url, expected=dict)
        if result is None:
            return []
        return self.records("who", result.get("value"))

    def paho(self):
        tree = self.request("paho", "https://www.paho.org/en/rss.xml", xml=True,
                            headers={"Accept": "application/rss+xml,application/xml"})
        if tree is None:
            return []
        items = tree.findall(".//item")
        if not items:
            self.error("paho", "RSS feed contains no items")
        return self.records("paho", [{"title": item.findtext("title") or "",
            "description": item.findtext("description") or "",
            "url": item.findtext("link") or "", "published": item.findtext("pubDate") or ""}
            for item in items[:40]])

    def news(self):
        queries = ['(outbreak OR epidemic) (dengue OR cholera OR measles OR mpox)',
                   '(outbreak OR cases) (ebola OR marburg OR nipah OR "avian flu")',
                   '"unexplained illness" OR "mystery illness"']
        out = []
        for index, query in enumerate(queries):
            if index:
                self.sleep(10)
            params = urllib.parse.urlencode({"query": query, "mode": "ArtList", "format": "json",
                "maxrecords": "75", "sort": "DateDesc", "timespan": "7d"})
            result = self.request("news", "https://api.gdeltproject.org/api/v2/doc/doc?" + params, expected=dict)
            if result is not None:
                articles = result.get("articles")
                if not isinstance(articles, list):
                    self.error("news", "Missing articles list")
                    continue
                rows = []
                for article in articles:
                    if not isinstance(article, dict):
                        self.error("news", "Malformed article skipped")
                        continue
                    rows.append({"title": article.get("title") or "", "url": article.get("url") or "",
                                 "published": article.get("seendate") or "", "date_basis": "gdelt_index"})
                out.extend(self.records("news", rows, query))
            if "HTTP 429" in self.health["news"]["errors"]:
                break
        return out

    def mastodon(self):
        out = []
        tags = ["outbreak", "ebola", "cholera", "dengue", "mpox", "measles", "h5n1", "travelhealth"]
        for tag in tags:
            result = None
            for host in ("mastodon.social", "mstdn.social"):
                result = self.request("mastodon", f"https://{host}/api/v1/timelines/tag/{tag}?limit=30", expected=list)
                if result is not None:
                    break
            if result is not None:
                # A boost is a second retrieval of the original document.
                originals = [r.get("reblog") or r if isinstance(r, dict) else r for r in result]
                out.extend(self.records("mastodon", originals, "#" + tag))
            self.sleep(1)
        return out

    def reddit(self):
        client = os.environ.get("REDDIT_CLIENT_ID", "").strip()
        secret = os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
        if not client or not secret:
            self.health["reddit"]["status"] = "disabled"
            self.health["reddit"]["errors"] = ["Credentials not configured"]
            return []
        auth = base64.b64encode(f"{client}:{secret}".encode()).decode()
        result = self.request("reddit", "https://www.reddit.com/api/v1/access_token",
            headers={"Authorization": "Basic " + auth},
            data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode(), expected=dict)
        if result is None or not isinstance(result.get("access_token"), str):
            self.error("reddit", "Authentication unavailable")
            return []
        params = urllib.parse.urlencode({"q": '(dengue OR malaria OR illness) (travel OR trip)',
                                         "limit": "50", "sort": "new", "t": "month"})
        feed = self.request("reddit", "https://oauth.reddit.com/search?" + params,
                            headers={"Authorization": "Bearer " + result["access_token"]}, expected=dict)
        if feed is None:
            return []
        children = feed.get("data", {}).get("children")
        if not isinstance(children, list):
            self.error("reddit", "Missing Reddit post list")
            return []
        rows = []
        for child in children:
            post = child.get("data", {}) if isinstance(child, dict) else {}
            rows.append({"title": post.get("title") or "", "description": post.get("selftext") or "",
                         "url": "https://www.reddit.com" + (post.get("permalink") or ""),
                         "published": post.get("created_utc") or ""})
        return self.records("reddit", rows, "travel illness")

    def collect(self):
        results = {}
        for source, method in (("who", self.who), ("paho", self.paho), ("news", self.news),
                               ("mastodon", self.mastodon), ("reddit", self.reddit)):
            try:
                results[source] = method()
            except (ValueError, TypeError, AttributeError, KeyError, OverflowError):
                self.error(source, "Unexpected feed shape; source skipped")
                results[source] = []
            print(f"{SOURCES[source]}: {self.health[source]['status']}, {len(results[source])} items", flush=True)
        return results
