import contextlib

import pytest

from src.main import app


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
    scraper = _guard_stub()
    calls = []

    class FakePage:
        async def route(self, pattern, handler):
            calls.append(("route", pattern, handler))

        async def goto(self, *args, **kwargs):
            calls.append(("goto",))

        async def wait_for_timeout(self, *args):
            pass

        async def content(self):
            return "<p>ok</p>"

        async def close(self):
            pass

    class FakeBrowser:
        async def new_page(self):
            return FakePage()

    async def fake_browser():
        return FakeBrowser()

    monkeypatch.setattr(scraper, "_get_browser", fake_browser)

    assert await scraper.fetch_page_js("https://vendor.example/p") == "<p>ok</p>"
    assert calls[0] == ("route", "**/*", scraper._guard_browser_request)
    assert calls[1] == ("goto",)


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

    scraper = _guard_stub()
    try:
        await scraper._get_browser()
    except Exception as exc:
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
