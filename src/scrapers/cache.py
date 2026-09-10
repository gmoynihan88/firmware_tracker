"""An on-disk response cache, for not hammering vendors during development.

Scheduled scraping is polite by construction: four runs a day, one second between
requests. Development is not. Debugging a single scraper means running it over and
over, and every one of those runs refetched every page from the vendor -- for data
that had not changed since the run a minute earlier.

This is off by default, so production keeps fetching live. Turn it on while working
on a scraper:

    SCRAPE_CACHE=1 .venv/bin/python -c "..."

Entries are keyed on the whole request, not just the URL, because Modartt selects a
product with a POST body and Steinberg with a query string -- keying on the URL alone
would serve one product's changelog for another.
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Optional


class ResponseCache:
    """A content cache keyed on the full request, with a TTL.

    Stores bodies as files rather than in one index, so a corrupt or truncated entry
    costs a single URL rather than the whole cache. A miss is always safe: the caller
    just fetches, which is what it would have done anyway.
    """

    def __init__(self, directory: Path, ttl_seconds: float):
        self.directory = Path(directory)
        self.ttl_seconds = ttl_seconds

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    @staticmethod
    def key(method: str, url: str, body: Optional[str] = None) -> str:
        raw = f"{method.upper()} {url}\n{body or ''}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def get(self, method: str, url: str, body: Optional[str] = None) -> Optional[str]:
        """Return a cached body, or None if absent, expired or unreadable."""
        path = self._path(self.key(method, url, body))
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Missing, unreadable or half-written. Treat every failure as a miss --
            # a cache that raises is worse than no cache.
            return None

        if time.time() - entry.get("fetched_at", 0) > self.ttl_seconds:
            return None
        return entry.get("body")

    def set(self, method: str, url: str, body: str, request_body: Optional[str] = None) -> None:
        """Store a body. Failures are ignored; the caller already has its answer."""
        path = self._path(self.key(method, url, request_body))
        entry = {
            "url": url,
            "method": method.upper(),
            "fetched_at": time.time(),
            "body": body,
        }
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            # Write beside the target and rename, so an interrupted write cannot
            # leave a truncated entry that reads as valid.
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(entry), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass
