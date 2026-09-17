import asyncio

import pytest


def _scraper():
    from src.scrapers.base import BaseScraper

    class Probe(BaseScraper):
        manufacturer_name, manufacturer_slug = "Probe", "probe"
        manufacturer_website = "https://example.invalid"

        async def fetch_device_list(self):
            ...

        async def fetch_firmware_versions(self, device_name, firmware_page_url):
            ...

    scraper = Probe()
    # Straight to the network path: no cache, no rate-limit sleeps between attempts.
    scraper._cache = None
    scraper._serve_from_cache = False
    scraper._revalidate = False

    async def no_wait():
        return None

    scraper._rate_limit = no_wait
    return scraper


class _Response:
    def __init__(self, status):
        self.status = status
        self.headers = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Session:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return _Response(self.outcome)


def _with_session(scraper, session):
    async def fake_session():
        return session

    scraper._get_session = fake_session
    return session


@pytest.mark.asyncio
async def test_a_fetch_that_breaks_is_recorded_and_a_404_is_not():
    """A timeout or a 5xx is a page that should have loaded; a 404 is an answer.

    Scrapers probe URLs that are allowed to be missing, so counting 404s would bury
    the failures this exists to surface.
    """
    timed_out = _scraper()
    _with_session(timed_out, _Session(asyncio.TimeoutError()))
    assert await timed_out.fetch_page("https://v.example/slow") is None
    assert timed_out.fetch_failures() == ["https://v.example/slow: TimeoutError"]

    unavailable = _scraper()
    _with_session(unavailable, _Session(503))
    assert await unavailable.fetch_page("https://v.example/busy") is None
    assert unavailable.fetch_failures() == ["https://v.example/busy: HTTP 503"]

    missing = _scraper()
    _with_session(missing, _Session(404))
    assert await missing.fetch_page("https://v.example/nope") is None
    assert missing.fetch_failures() == []


@pytest.mark.asyncio
async def test_fetch_page_takes_a_longer_timeout_only_when_asked():
    scraper = _scraper()
    session = _with_session(scraper, _Session(404))

    await scraper.fetch_page("https://v.example/a")
    await scraper.fetch_page("https://v.example/b", timeout=90)

    assert "timeout" not in session.calls[0]
    assert session.calls[1]["timeout"].total == 90


class TimeoutError(Exception):
    """Named like Playwright's, which is how the retry recognises a navigation timeout."""


def _browser_with(outcomes, calls):
    from tests.support import fake_browser

    class FakePage:
        async def goto(self, *args, **kwargs):
            calls.append("goto")
            outcome = outcomes.pop(0)
            if outcome is not None:
                raise outcome

        async def wait_for_timeout(self, *args):
            pass

        async def content(self):
            return "<p>rendered</p>"

        async def close(self):
            pass

    return fake_browser(FakePage())


@pytest.mark.asyncio
async def test_a_rendered_page_that_times_out_is_tried_once_more():
    """TAL's pages were slow for a few minutes and fine after; one retry covers that."""
    scraper = _scraper()
    calls = []
    scraper._get_browser = _browser_with([TimeoutError("Timeout 20000ms exceeded"), None], calls)

    assert await scraper.fetch_page_js("https://v.example/p", wait_for_timeout=20000) == "<p>rendered</p>"
    assert calls == ["goto", "goto"]
    assert scraper.fetch_failures() == []


@pytest.mark.asyncio
async def test_a_rendered_page_is_retried_only_for_a_timeout_and_only_once():
    slow = _scraper()
    calls = []
    slow._get_browser = _browser_with([TimeoutError("Timeout"), TimeoutError("Timeout")], calls)
    assert await slow.fetch_page_js("https://v.example/slow") is None
    assert calls == ["goto", "goto"]
    assert slow.fetch_failures() == ["https://v.example/slow: TimeoutError"]

    refused = _scraper()
    calls = []
    refused._get_browser = _browser_with([RuntimeError("net::ERR_ABORTED")], calls)
    assert await refused.fetch_page_js("https://v.example/refused") is None
    assert calls == ["goto"]
    assert refused.fetch_failures() == ["https://v.example/refused: RuntimeError"]
