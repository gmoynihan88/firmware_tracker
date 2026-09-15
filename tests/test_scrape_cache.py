import json
import time

import pytest


def test_response_cache_separates_requests_that_differ_only_by_body(tmp_path):
    """Modartt picks a product with a POST body, so the URL alone is not the key.

    Keying on the URL would serve one product's changelog for another -- silently,
    and only while the cache is on, which is the worst way to find a bug.
    """
    from src.scrapers.cache import ResponseCache

    cache = ResponseCache(tmp_path, ttl_seconds=3600)
    cache.set("POST", "https://api.example/products", "pianoteq data", '{"software":"pianoteq"}')
    cache.set("POST", "https://api.example/products", "organteq data", '{"software":"organteq"}')

    assert cache.get("POST", "https://api.example/products", '{"software":"pianoteq"}') == "pianoteq data"
    assert cache.get("POST", "https://api.example/products", '{"software":"organteq"}') == "organteq data"
    # A body that was never stored is a miss, not somebody else's answer.
    assert cache.get("POST", "https://api.example/products", '{"software":"other"}') is None


def test_response_cache_expires_and_survives_corruption(tmp_path):
    from src.scrapers.cache import ResponseCache

    expired = ResponseCache(tmp_path, ttl_seconds=0)
    expired.set("GET", "https://example.invalid/a", "stale")
    assert expired.get("GET", "https://example.invalid/a") is None

    # A truncated or garbage entry must read as a miss rather than raising, so a
    # damaged cache degrades to fetching rather than breaking every scraper.
    fresh = ResponseCache(tmp_path, ttl_seconds=3600)
    fresh.set("GET", "https://example.invalid/b", "good")
    (tmp_path / f"{ResponseCache.key('GET', 'https://example.invalid/b')}.json").write_text("{not json")
    assert fresh.get("GET", "https://example.invalid/b") is None


def test_serving_from_cache_is_off_by_default():
    """Shipped defaults must fetch live. Read from Settings, not the developer's .env.

    The declared field defaults are read, not an instance. _env_file=None blocks the
    .env file but pydantic still reads environment variables, so an instance would
    assert whatever the developer last exported -- and this machine has
    SCRAPE_CACHE=true set for debugging.
    """
    from src.config import Settings

    assert Settings.model_fields["scrape_cache"].default is False
    assert Settings.model_fields["http_revalidate"].default is True


@pytest.mark.asyncio
async def test_the_store_exists_for_validators_but_never_answers_on_its_own(monkeypatch):
    """Revalidation keeps a store in production, and that must not serve stale bodies.

    The store exists whenever revalidation is on, because conditional requests need
    somewhere to keep validators. If its presence alone were enough to short-circuit a
    fetch, turning revalidation on would quietly stop the app finding new firmware.
    """
    from src.config import Settings
    from src.scrapers.plugins import steinberg as module

    # Stated explicitly rather than relying on defaults: env vars reach Settings even
    # with _env_file=None, so this pins the production combination under any shell.
    production = Settings(_env_file=None, scrape_cache=False, http_revalidate=True)
    monkeypatch.setattr("src.scrapers.base.get_settings", lambda: production)

    scraper = module.SteinbergScraper()

    assert scraper._cache is not None          # needed to hold ETags
    assert scraper._serve_from_cache is False  # but never answers without asking
    assert scraper._revalidate is True


@pytest.mark.asyncio
async def test_fetch_page_js_keys_on_the_click_selector(tmp_path, monkeypatch):
    """Clicking a tab changes what renders, so the same URL is a different response."""
    from src.scrapers.base import BaseScraper
    from src.scrapers.cache import ResponseCache

    class Stub(BaseScraper):
        manufacturer_name, manufacturer_slug, manufacturer_website = "S", "s", "https://e.invalid"

        async def fetch_device_list(self):
            ...

        async def fetch_firmware_versions(self, device_name, firmware_page_url):
            ...

    scraper = Stub()
    scraper._cache = ResponseCache(tmp_path, ttl_seconds=3600)
    # Rendered pages are only served from the development cache; the store alone is
    # not enough, or production would answer from disk without asking the vendor.
    scraper._serve_from_cache = True

    # Prime the cache as if the two tabs had been fetched.
    import json as _json

    for click, html in (("#tab-a", "<p>A</p>"), ("#tab-b", "<p>B</p>")):
        variant = _json.dumps({"click": click, "wait": None}, sort_keys=True)
        scraper._cache.set("GET-JS", "https://e.invalid/p", html, variant)

    # Playwright must never be reached; a hit returns before the browser launches.
    async def explode():
        raise AssertionError("cache hit should not launch a browser")

    monkeypatch.setattr(scraper, "_get_browser", explode)

    assert await scraper.fetch_page_js("https://e.invalid/p", click_selector="#tab-a") == "<p>A</p>"
    assert await scraper.fetch_page_js("https://e.invalid/p", click_selector="#tab-b") == "<p>B</p>"


def test_conditional_headers_need_a_body_to_fall_back_on(tmp_path):
    """Sending If-None-Match with no stored body would earn a 304 carrying nothing.

    The caller would be left with no content and no way to parse it, so an entry
    without a body must not produce conditional headers at all.
    """
    from src.scrapers.cache import ResponseCache

    assert ResponseCache.conditional_headers(None) == {}
    assert ResponseCache.conditional_headers({"etag": 'W/"abc"', "body": ""}) == {}
    assert ResponseCache.conditional_headers({"etag": 'W/"abc"', "body": "<html>"}) == {
        "If-None-Match": 'W/"abc"'
    }
    assert ResponseCache.conditional_headers(
        {"last_modified": "Wed, 10 Sep 2026 00:00:00 GMT", "body": "<html>"}
    ) == {"If-Modified-Since": "Wed, 10 Sep 2026 00:00:00 GMT"}


def test_entry_ignores_ttl_but_get_respects_it(tmp_path):
    """A stale entry is still what revalidation needs: its ETag earns the 304.

    get() is the development path and must expire; entry() is the revalidation path
    and must not, or an old-but-valid ETag would never be sent.
    """
    from src.scrapers.cache import ResponseCache

    cache = ResponseCache(tmp_path, ttl_seconds=0)
    cache.set("GET", "https://example.invalid/p", "<html>", etag='W/"abc"')

    assert cache.get("GET", "https://example.invalid/p") is None
    stored = cache.entry("GET", "https://example.invalid/p")
    assert stored["body"] == "<html>"
    assert ResponseCache.conditional_headers(stored) == {"If-None-Match": 'W/"abc"'}


def test_touch_refreshes_age_without_losing_the_body(tmp_path):
    """A 304 confirms the stored copy is current, so its age resets but not its content."""
    from src.scrapers.cache import ResponseCache

    cache = ResponseCache(tmp_path, ttl_seconds=3600)
    cache.set("GET", "https://example.invalid/p", "<html>", etag='W/"abc"')
    before = cache.entry("GET", "https://example.invalid/p")["fetched_at"]

    time.sleep(0.01)
    cache.touch("GET", "https://example.invalid/p")
    after = cache.entry("GET", "https://example.invalid/p")

    assert after["fetched_at"] > before
    assert after["body"] == "<html>"
    assert after["etag"] == 'W/"abc"'


def test_prune_drops_only_what_has_gone_quiet(tmp_path):
    """A 304 touches its entry, so live pages stay young; dead URLs age out."""
    from src.scrapers.cache import ResponseCache

    cache = ResponseCache(tmp_path, ttl_seconds=3600)
    cache.set("GET", "https://example.invalid/live", "<html>")
    cache.set("GET", "https://example.invalid/dead", "<html>")

    # Age the second entry past the cutoff.
    dead = tmp_path / f"{ResponseCache.key('GET', 'https://example.invalid/dead')}.json"
    entry = json.loads(dead.read_text())
    entry["fetched_at"] -= 86400 * 30
    dead.write_text(json.dumps(entry))

    assert cache.prune(86400 * 14) == 1
    assert cache.entry("GET", "https://example.invalid/live") is not None
    assert cache.entry("GET", "https://example.invalid/dead") is None
