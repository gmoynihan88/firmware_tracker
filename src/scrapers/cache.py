"""An on-disk response store, for not hammering vendors.

Two things use it, and they are separate knobs:

`SCRAPE_CACHE` (off by default) serves a stored body straight back without touching
the network at all, for up to `SCRAPE_CACHE_TTL_HOURS`. That is a development tool.
Debugging a scraper means running it over and over against data that has not changed,
and without this the vendor serves every one of those runs.

`HTTP_REVALIDATE` (on by default) is the production one. It keeps each response's
`ETag` and `Last-Modified` and sends them back as `If-None-Match` /
`If-Modified-Since` on the next fetch. A vendor that recognises them answers `304 Not
Modified` with no body, which costs them a header exchange instead of a page.

Only about a quarter of the tracked vendors send a validator -- most answer
`no-store` -- so this is a real but partial saving. The ones it helps are the large
CDN-backed sites; the small operations send nothing, and for them the only levers are
the scrape interval and the development cache above.

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
    """A content store keyed on the full request, holding bodies and validators.

    Stores each entry as its own file rather than in one index, so a corrupt or
    truncated entry costs a single URL rather than the whole cache. Every read
    failure is a miss, and a miss is always safe: the caller fetches, which is what
    it would have done anyway.
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

    def entry(self, method: str, url: str, body: Optional[str] = None) -> Optional[dict]:
        """Return the stored entry regardless of age, or None if unreadable.

        Age is deliberately not checked here. A stale entry is still exactly what
        revalidation needs: its validators are what earn the 304, and its body is
        what the 304 lets us reuse.
        """
        try:
            return json.loads(self._path(self.key(method, url, body)).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Missing, unreadable or half-written. A cache that raises is worse than
            # no cache.
            return None

    def get(self, method: str, url: str, body: Optional[str] = None) -> Optional[str]:
        """Return a cached body only if it is still within the TTL."""
        found = self.entry(method, url, body)
        if not found:
            return None
        if time.time() - found.get("fetched_at", 0) > self.ttl_seconds:
            return None
        return found.get("body")

    @staticmethod
    def conditional_headers(found: Optional[dict]) -> dict:
        """Build the request headers that ask the server 'has this changed?'.

        Returns nothing unless there is a body to fall back on. Sending
        If-None-Match without a stored body would invite a 304 carrying nothing,
        leaving the caller with no content and no way to parse it.
        """
        if not found or not found.get("body"):
            return {}
        headers = {}
        if found.get("etag"):
            headers["If-None-Match"] = found["etag"]
        if found.get("last_modified"):
            headers["If-Modified-Since"] = found["last_modified"]
        return headers

    def set(
        self,
        method: str,
        url: str,
        body: str,
        request_body: Optional[str] = None,
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
    ) -> None:
        """Store a body and any validators. Failures are ignored -- the caller
        already has its answer, and losing a cache write is not worth an exception."""
        self._write(
            self.key(method, url, request_body),
            {
                "url": url,
                "method": method.upper(),
                "fetched_at": time.time(),
                "etag": etag,
                "last_modified": last_modified,
                "body": body,
            },
        )

    def touch(self, method: str, url: str, request_body: Optional[str] = None) -> None:
        """Mark an entry as confirmed-current after a 304, without rewriting the body."""
        found = self.entry(method, url, request_body)
        if not found:
            return
        found["fetched_at"] = time.time()
        self._write(self.key(method, url, request_body), found)

    def prune(self, max_age_seconds: float) -> int:
        """Delete entries not seen for a while, and report how many went.

        Revalidation keeps bodies on disk in production, so without this the store
        grows without limit -- and it keeps a copy of every page a scraper ever
        fetched, including ones whose product has since been removed. A 304 calls
        touch(), so anything still in use stays young.
        """
        cutoff = time.time() - max_age_seconds
        removed = 0
        try:
            paths = list(self.directory.glob("*.json"))
        except OSError:
            return 0
        for path in paths:
            try:
                if json.loads(path.read_text(encoding="utf-8")).get("fetched_at", 0) < cutoff:
                    path.unlink()
                    removed += 1
            except (OSError, ValueError):
                # Unreadable entries are useless anyway; drop them.
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed

    def _write(self, key: str, entry: dict) -> None:
        path = self._path(key)
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            # Write beside the target and rename, so an interrupted write cannot
            # leave a truncated entry that still parses.
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(entry), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass
