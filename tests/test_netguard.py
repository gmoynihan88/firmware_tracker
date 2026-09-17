import contextlib

import pytest

from src.main import app
from tests.support import chromium_is_installed


@contextlib.asynccontextmanager
async def _local_server(routes):
    """An aiohttp server on 127.0.0.1 that records every path it is asked for."""
    from aiohttp import web

    hits = []
    app = web.Application()
    for path, handler in routes.items():
        async def recorded(request, _handler=handler):
            hits.append(request.path)
            return await _handler(request)

        app.router.add_get(path, recorded)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    try:
        yield runner.addresses[0][1], hits
    finally:
        await runner.cleanup()


def _guard_stub(**settings):
    from src.scrapers.base import BaseScraper

    class Stub(BaseScraper):
        manufacturer_name, manufacturer_slug, manufacturer_website = "S", "s", "https://e.invalid"

        async def fetch_device_list(self):
            ...

        async def fetch_firmware_versions(self, device_name, firmware_page_url):
            ...

    scraper = Stub()
    scraper._cache = None
    scraper._serve_from_cache = False
    scraper._revalidate = False
    scraper.settings = scraper.settings.model_copy(
        update={"rate_limit_delay": 0, "request_timeout": 5, **settings}
    )
    return scraper


@pytest.fixture
def allow_loopback(monkeypatch):
    """Let the guard reach a test server on loopback, and nothing else it refuses."""
    import ipaddress

    from src.scrapers import netguard

    def allowed(address):
        return netguard.is_public_address(address) or ipaddress.ip_address(address).is_loopback

    monkeypatch.setattr(netguard, "address_allowed", allowed)


@pytest.mark.parametrize("address, public", [
    ("93.184.216.34", True),
    ("2606:4700:4700::1111", True),
    ("::ffff:93.184.216.34", True),
    ("127.0.0.1", False),
    ("10.0.0.8", False),
    ("172.16.4.4", False),
    ("192.168.1.10", False),
    ("169.254.169.254", False),   # EC2 instance metadata
    ("169.254.170.2", False),     # ECS task credentials
    ("100.64.0.1", False),        # carrier-grade NAT
    ("0.0.0.0", False),
    ("224.0.0.1", False),
    ("::1", False),
    ("fe80::1", False),
    ("fd00::1", False),
    ("::ffff:127.0.0.1", False),  # IPv4 loopback wearing IPv6
    ("not-an-address", False),
])
def test_netguard_knows_which_addresses_are_public(address, public):
    from src.scrapers.netguard import is_public_address

    assert is_public_address(address) is public


@pytest.mark.asyncio
async def test_netguard_positive_control_reaches_the_server_when_allowed(allow_loopback):
    """Without this, a guard that refused everything would pass every test below."""
    from aiohttp import web

    async def ok(request):
        return web.Response(text="<p>ok</p>", content_type="text/html")

    scraper = _guard_stub()
    async with _local_server({"/": ok}) as (port, hits):
        body = await scraper.fetch_page(f"http://127.0.0.1:{port}/")
    await scraper.close()

    assert body == "<p>ok</p>"
    assert hits == ["/"]


@pytest.mark.asyncio
async def test_fetch_page_refuses_a_literal_private_address(caplog):
    """aiohttp skips the resolver for an IP literal, so this is the trace's job."""
    from aiohttp import web

    async def ok(request):
        return web.Response(text="<p>should never be served</p>")

    scraper = _guard_stub()
    async with _local_server({"/": ok}) as (port, hits):
        with caplog.at_level("WARNING"):
            body = await scraper.fetch_page(f"http://127.0.0.1:{port}/")
    await scraper.close()

    assert body is None
    assert hits == []
    assert "non-public" in caplog.text


@pytest.mark.asyncio
async def test_fetch_page_refuses_a_name_that_resolves_privately(caplog):
    """`localhost` is a name, so it reaches the resolver -- which refuses it."""
    from aiohttp import web

    async def ok(request):
        return web.Response(text="<p>should never be served</p>")

    scraper = _guard_stub()
    async with _local_server({"/": ok}) as (port, hits):
        with caplog.at_level("WARNING"):
            body = await scraper.fetch_page(f"http://localhost:{port}/")
    await scraper.close()

    assert body is None
    assert hits == []
    assert "non-public" in caplog.text


@pytest.mark.asyncio
async def test_fetch_page_refuses_a_redirect_into_the_network(allow_loopback, caplog):
    """The first hop is allowed; the Location it sends is the ECS credential endpoint.

    If the check ran only on the URL a scraper asked for, this would try to connect
    to 169.254.170.2 and fail on a timeout rather than being refused.
    """
    from aiohttp import web

    async def start(request):
        raise web.HTTPFound("http://169.254.170.2/v2/credentials")

    scraper = _guard_stub()
    async with _local_server({"/start": start}) as (port, hits):
        with caplog.at_level("WARNING"):
            body = await scraper.fetch_page(f"http://127.0.0.1:{port}/start")
    await scraper.close()

    assert body is None
    assert hits == ["/start"]
    assert "non-public" in caplog.text


@pytest.mark.asyncio
async def test_fetch_json_goes_through_the_same_guard():
    from aiohttp import web

    async def api(request):
        return web.json_response({"leaked": True})

    scraper = _guard_stub()
    async with _local_server({"/api": api}) as (port, hits):
        data = await scraper.fetch_json(f"http://127.0.0.1:{port}/api")
    await scraper.close()

    assert data is None
    assert hits == []


@pytest.mark.asyncio
async def test_fetch_page_refuses_a_body_over_the_cap(allow_loopback, caplog):
    """Both ways a body arrives: with a declared length, and streamed without one."""
    from aiohttp import web

    async def declared(request):
        return web.Response(text="x" * 5000)

    async def streamed(request):
        response = web.StreamResponse()
        await response.prepare(request)
        for _ in range(5):
            await response.write(b"x" * 1000)
        await response.write_eof()
        return response

    async def small(request):
        return web.Response(text="x" * 500)

    scraper = _guard_stub(max_response_bytes=2000)
    async with _local_server({"/declared": declared, "/streamed": streamed, "/small": small}) as (port, _):
        base = f"http://127.0.0.1:{port}"
        with caplog.at_level("WARNING"):
            assert await scraper.fetch_page(f"{base}/declared") is None
            assert await scraper.fetch_page(f"{base}/streamed") is None
        assert await scraper.fetch_page(f"{base}/small") == "x" * 500
    await scraper.close()

    assert "declares 5000 bytes" in caplog.text
    assert "exceeded the 2000-byte cap" in caplog.text


@pytest.mark.asyncio
async def test_capped_read_decodes_exactly_like_response_text(allow_loopback):
    """A page that decoded before the cap must decode identically after it."""
    import aiohttp
    from aiohttp import web

    async def latin1(request):
        return web.Response(
            body="Café résumé".encode("latin-1"),
            headers={"Content-Type": "text/html; charset=iso-8859-1"},
        )

    async def utf8_without_charset(request):
        return web.Response(
            body="Café ✓".encode("utf-8"),
            headers={"Content-Type": "text/html"},
        )

    async def unknown_charset(request):
        return web.Response(
            body="Café".encode("utf-8"),
            headers={"Content-Type": "text/html; charset=not-a-real-codec"},
        )

    async def json_body(request):
        return web.Response(
            body='{"name": "Café"}'.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

    routes = {
        "/latin1": latin1,
        "/utf8": utf8_without_charset,
        "/unknown": unknown_charset,
        "/json": json_body,
    }
    scraper = _guard_stub()
    async with _local_server(routes) as (port, _):
        async with aiohttp.ClientSession() as plain:
            for path in routes:
                url = f"http://127.0.0.1:{port}{path}"
                async with plain.get(url) as response:
                    expected = await response.text()
                assert await scraper.fetch_page(url) == expected, path
    await scraper.close()


@pytest.mark.asyncio
async def test_capped_read_falls_back_to_cp1252_for_undeclared_non_utf8_text(allow_loopback):
    """REAPER's changelog is Windows-1252 with no charset; strict UTF-8 lost the whole file."""
    from aiohttp import web

    async def windows_text(request):
        return web.Response(
            body="v7.80 - September 13 2026\n  + Caf\u00e9 \u2013 r\u00e9sum\u00e9".encode("cp1252"),
            headers={"Content-Type": "text/plain"},
        )

    async def lying_charset(request):
        return web.Response(
            body="Caf\u00e9".encode("cp1252"),
            headers={"Content-Type": "text/plain; charset=utf-8"},
        )

    scraper = _guard_stub()
    async with _local_server({"/whatsnew.txt": windows_text, "/lying": lying_charset}) as (port, _):
        text = await scraper.fetch_page(f"http://127.0.0.1:{port}/whatsnew.txt")
        # A declared charset the body contradicts still fails rather than guessing.
        lying = await scraper.fetch_page(f"http://127.0.0.1:{port}/lying")
    await scraper.close()

    assert text == "v7.80 - September 13 2026\n  + Caf\u00e9 \u2013 r\u00e9sum\u00e9"
    assert lying is None


class _FakeRoute:
    def __init__(self, url):
        self.request = type("Request", (), {"url": url})()
        self.outcome = None

    async def continue_(self):
        self.outcome = "continue"

    async def abort(self, error_code=None):
        self.outcome = ("abort", error_code)


@pytest.mark.asyncio
async def test_rendered_requests_are_checked_one_by_one(monkeypatch):
    """A rendered page's own scripts choose what loads, so every request is checked."""
    from src.scrapers import netguard

    lookups = []
    answers = {"vendor.example": ["93.184.216.34"], "rebind.example": ["10.0.0.5"]}

    async def fake_resolve(host):
        lookups.append(host)
        if host not in answers:
            raise OSError("no such host")
        return answers[host]

    monkeypatch.setattr(netguard, "_resolve", fake_resolve)
    scraper = _guard_stub()
    blocked = ("abort", "blockedbyclient")

    cases = [
        ("https://vendor.example/downloads", "continue"),
        ("https://vendor.example/app.js", "continue"),     # same host: one lookup
        ("https://rebind.example/x", blocked),             # a name pointing inside
        ("http://169.254.170.2/v2/credentials", blocked),  # literal metadata address
        ("http://[::1]:8000/", blocked),
        ("https://nxdomain.example/", blocked),            # unresolvable fails closed
        ("data:image/png;base64,AAAA", "continue"),
        ("file:///etc/passwd", blocked),
    ]
    for url, expected in cases:
        route = _FakeRoute(url)
        await scraper._guard_browser_request(route)
        assert route.outcome == expected, url

    assert lookups.count("vendor.example") == 1


@pytest.mark.asyncio
async def test_fetch_page_js_installs_the_guard_before_navigating(monkeypatch):
    """The guard only protects a page if it is in place before the first request."""
    from tests.support import fake_browser

    scraper = _guard_stub()
    calls = []

    class FakePage:
        async def goto(self, *args, **kwargs):
            calls.append(("goto",))

        async def wait_for_timeout(self, *args):
            pass

        async def content(self):
            return "<p>ok</p>"

        async def close(self):
            pass

    monkeypatch.setattr(scraper, "_get_browser", fake_browser(FakePage(), calls))

    assert await scraper.fetch_page_js("https://vendor.example/p") == "<p>ok</p>"
    steps = [c[0] for c in calls]
    assert steps.index("route") < steps.index("new_page") < steps.index("goto")
    assert ("route", "**/*", scraper._guard_browser_request) in calls


@pytest.mark.asyncio
async def test_a_rendered_fetch_blocks_service_workers(monkeypatch):
    """A worker's own fetches are not routed, so the only defence is not having one.

    Measured: a service worker fetched from inside its install handler and the guard
    never saw the request.
    """
    from tests.support import fake_browser

    scraper = _guard_stub()
    calls = []

    class FakePage:
        async def goto(self, *args, **kwargs):
            return None

        async def wait_for_timeout(self, *args):
            pass

        async def content(self):
            return "<p>ok</p>"

        async def close(self):
            pass

    monkeypatch.setattr(scraper, "_get_browser", fake_browser(FakePage(), calls))
    await scraper.fetch_page_js("https://vendor.example/p")

    context = next(c for c in calls if c[0] == "context")
    assert context[1].get("service_workers") == "block"


@pytest.mark.asyncio
async def test_a_rendered_fetch_closes_the_whole_context(monkeypatch):
    """Closing the page alone would leave every window it opened running.

    Popups are deliberately not closed as they appear -- racing Playwright's
    asynchronous route attachment let their own fetches escape the guard. What keeps
    them from outliving the fetch is the context being closed here, so a change back
    to closing only the page would leak them.
    """
    from tests.support import fake_browser

    scraper = _guard_stub()
    calls = []

    class FakePage:
        async def goto(self, *args, **kwargs):
            return None

        async def wait_for_timeout(self, *args):
            pass

        async def content(self):
            return "<p>opener</p>"

        async def close(self):
            calls.append(("page_close",))

    monkeypatch.setattr(scraper, "_get_browser", fake_browser(FakePage(), calls))
    assert await scraper.fetch_page_js("https://vendor.example/p") == "<p>opener</p>"

    assert ("close",) in calls, "the context was never closed, so popups would survive"


class _FakeRequest:
    """One hop of a navigation, shaped like Playwright's Request."""

    def __init__(self, url, redirected_from=None):
        self.url = url
        self.redirected_from = redirected_from


class _FakeResponse:
    def __init__(self, chain):
        """`chain` runs oldest first, the way a redirect actually happens."""
        request = None
        for url in chain:
            request = _FakeRequest(url, request)
        self.request = request


def _redirecting_browser(monkeypatch, scraper, chain):
    """A page whose navigation followed `chain` and rendered the last URL in it."""
    from tests.support import fake_browser

    class FakePage:
        async def goto(self, *args, **kwargs):
            return _FakeResponse(chain)

        async def wait_for_timeout(self, *args):
            pass

        async def content(self):
            return "<p>SECRET_BODY</p>"

        async def close(self):
            pass

    monkeypatch.setattr(scraper, "_get_browser", fake_browser(FakePage()))


def _resolving(monkeypatch, answers):
    from src.scrapers import netguard

    async def fake_resolve(host):
        if host not in answers:
            raise OSError("no such host")
        return answers[host]

    monkeypatch.setattr(netguard, "_resolve", fake_resolve)


@pytest.mark.asyncio
async def test_a_rendered_redirect_into_the_network_never_reaches_the_caller(
    monkeypatch, caplog
):
    """The hole this check exists for.

    Chromium does not re-invoke a `page.route` handler for the target of a redirect it
    follows -- verified against the project's own Chromium, where the handler recorded
    only the first URL while the redirect target was fetched, served and returned by
    `page.content()`. So a vendor answering 302 to the task's credential endpoint had
    that response parsed like any other page, and scraped text is rendered on a public
    catalogue.

    The request itself cannot be recalled by the time anything here can look. What is
    refused is the body: the caller is told nothing loaded.
    """
    scraper = _guard_stub()
    _resolving(monkeypatch, {"vendor.example": ["93.184.216.34"]})
    _redirecting_browser(
        monkeypatch,
        scraper,
        [
            "https://vendor.example/downloads",
            "http://169.254.170.2/v2/credentials",
        ],
    )

    with caplog.at_level("WARNING"):
        result = await scraper.fetch_page_js("https://vendor.example/downloads")

    assert result is None, "a redirect into the network returned its body to the caller"
    assert "SECRET_BODY" not in (result or "")
    assert "169.254.170.2" in caplog.text
    # Recorded rather than silent: a scraper that skips a product must say why.
    assert any("BlockedRedirect" in failure for failure in scraper.fetch_failures())


@pytest.mark.asyncio
async def test_an_ordinary_redirect_still_returns_the_page(monkeypatch):
    """The other half. A guard that refuses http -> https would block most vendors."""
    scraper = _guard_stub()
    _resolving(
        monkeypatch,
        {"vendor.example": ["93.184.216.34"], "www.vendor.example": ["93.184.216.34"]},
    )
    _redirecting_browser(
        monkeypatch,
        scraper,
        [
            "http://vendor.example/downloads",
            "https://www.vendor.example/en/downloads",
        ],
    )

    assert await scraper.fetch_page_js("http://vendor.example/downloads") == (
        "<p>SECRET_BODY</p>"
    )
    assert scraper.fetch_failures() == []


@pytest.mark.asyncio
async def test_a_navigation_with_no_response_is_not_treated_as_a_redirect(monkeypatch):
    """`page.goto` returns None for a same-document navigation, which is not a refusal."""
    scraper = _guard_stub()
    _redirecting_browser(monkeypatch, scraper, [])

    assert await scraper.fetch_page_js("https://vendor.example/p") == "<p>SECRET_BODY</p>"


@pytest.mark.asyncio
async def test_real_chromium_blocks_private_pages_and_subrequests(monkeypatch, caplog):
    """End to end in a real browser. Skipped where Chromium is not installed, as in CI."""
    import ipaddress

    from aiohttp import web

    from src.scrapers import base, netguard

    if not base.PLAYWRIGHT_AVAILABLE:
        pytest.skip("Playwright not installed")

    async def page(request):
        return web.Response(
            text='<html><body><p>rendered</p><img src="http://169.254.170.2/x.png"></body></html>',
            content_type="text/html",
        )

    # Decided before the browser is touched at all. _get_browser() starts Playwright's
    # driver as a subprocess and only then launches Chromium, so asking the question
    # where there is no browser costs a driver process to be told no.
    if not chromium_is_installed():
        pytest.skip("Chromium is not installed")

    scraper = _guard_stub()
    try:
        await scraper._get_browser()
    except Exception as exc:
        # Stop the driver this call has already started. Skipping from here jumps over
        # the finally below -- the only thing that closes the scraper -- which left a
        # subprocess transport to be finalised after the test's event loop had closed.
        # On 3.12 that surfaces as "Event loop is closed" through pytest's unraisable
        # hook: two of them on every CI run, on an otherwise green build.
        await scraper.close()
        pytest.skip(f"Chromium unavailable: {exc}")

    try:
        async with _local_server({"/": page}) as (port, hits):
            url = f"http://127.0.0.1:{port}/"

            # Navigation to a loopback page is refused outright.
            assert await scraper.fetch_page_js(url, wait_for_timeout=5000) is None
            assert hits == []

            # Allow loopback, and the page loads -- but its image aimed at the
            # metadata address does not.
            monkeypatch.setattr(
                netguard, "address_allowed",
                lambda a: netguard.is_public_address(a) or ipaddress.ip_address(a).is_loopback,
            )
            scraper._host_verdicts.clear()
            with caplog.at_level("WARNING"):
                html = await scraper.fetch_page_js(url, wait_for_timeout=5000)
            assert html is not None and "rendered" in html
            assert "/" in hits
            assert "Blocked rendered request to a non-public address: http://169.254.170.2/x.png" in caplog.text
    finally:
        await scraper.close()


class _SizedPage:
    """A rendered page of a chosen size, recording whether it was ever serialised.

    `measured` is what the browser reports for the DOM length, and defaults to the
    real length: a test sets it only when the two are meant to disagree.
    """

    def __init__(self, html, measured=None, evaluates=True):
        self.html = html
        self.measured = len(html) if measured is None else measured
        self.evaluates = evaluates
        self.content_calls = 0

    async def goto(self, *args, **kwargs):
        return None

    async def wait_for_timeout(self, *args):
        pass

    async def evaluate(self, expression):
        if not self.evaluates:
            raise RuntimeError("execution context was destroyed")
        return self.measured

    async def content(self):
        self.content_calls += 1
        return self.html

    async def close(self):
        pass


def _sized_browser(monkeypatch, scraper, page):
    from tests.support import fake_browser

    monkeypatch.setattr(scraper, "_get_browser", fake_browser(page))
    return page


@pytest.mark.asyncio
async def test_an_oversized_rendered_page_is_never_pulled_into_the_process(
    monkeypatch, caplog
):
    """The cap exists for the memory, so the page must not be serialised at all.

    Checking the size after `page.content()` would be checking a string that has
    already been allocated, which is the thing being defended against.
    """
    scraper = _guard_stub(max_response_bytes=2000)
    page = _sized_browser(monkeypatch, scraper, _SizedPage("<p>x</p>", measured=9999))

    with caplog.at_level("WARNING"):
        assert await scraper.fetch_page_js("https://vendor.example/huge") is None

    assert page.content_calls == 0, "the oversized page was serialised anyway"
    assert "over the 2000-byte cap" in caplog.text
    assert any("ResponseTooLarge" in failure for failure in scraper.fetch_failures())


@pytest.mark.asyncio
async def test_the_rendered_cap_holds_when_the_browser_cannot_measure_the_page(
    monkeypatch, caplog
):
    """The browser-side measurement is best-effort; the byte check is the guarantee."""
    scraper = _guard_stub(max_response_bytes=2000)
    page = _sized_browser(monkeypatch, scraper, _SizedPage("x" * 5000, evaluates=False))

    with caplog.at_level("WARNING"):
        assert await scraper.fetch_page_js("https://vendor.example/huge") is None

    assert page.content_calls == 1, "the fallback check needs the content to measure it"
    assert "rendered 5000 bytes, over the 2000-byte cap" in caplog.text


@pytest.mark.asyncio
async def test_the_rendered_cap_counts_utf8_bytes_rather_than_characters(
    monkeypatch, caplog
):
    """`.length` in the browser counts UTF-16 units, and CJK is three bytes in UTF-8.

    900 ideographic spaces measure 900 to the browser -- under the cap -- and 2,700
    bytes once encoded. Counting characters would let this through.
    """
    scraper = _guard_stub(max_response_bytes=2000)
    page = _sized_browser(monkeypatch, scraper, _SizedPage("　" * 900))

    with caplog.at_level("WARNING"):
        assert await scraper.fetch_page_js("https://vendor.example/cjk") is None

    assert page.content_calls == 1, "the browser-side check should have passed this"
    assert "rendered 2700 bytes, over the 2000-byte cap" in caplog.text


@pytest.mark.asyncio
async def test_a_rendered_page_under_the_cap_is_returned_unchanged(monkeypatch):
    scraper = _guard_stub(max_response_bytes=2000)
    page = _sized_browser(monkeypatch, scraper, _SizedPage("<p>ok</p>"))

    assert await scraper.fetch_page_js("https://vendor.example/p") == "<p>ok</p>"
    assert scraper.fetch_failures() == []
