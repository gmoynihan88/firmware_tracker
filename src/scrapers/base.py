import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
import asyncio
import hashlib
import json
import re
import aiohttp
from bs4 import BeautifulSoup

try:
    from playwright.async_api import async_playwright, Browser, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

from src.config import get_settings
from src.scrapers import netguard
from src.scrapers.cache import ResponseCache


@dataclass
class ScrapedDevice:
    """Represents a device discovered by a scraper."""
    name: str
    category: str
    firmware_page_url: Optional[str] = None
    product_url: Optional[str] = None

    # Why this product has no version, when the scraper knows. One of
    # FirmwareAvailability's values, or None for "nobody has established why",
    # which is the right answer unless the scraper's docstring can say how.
    firmware_availability: Optional[str] = None


@dataclass
class ScrapedFirmware:
    """Represents a firmware version discovered by a scraper."""
    version: str
    release_date: Optional[datetime] = None
    download_url: Optional[str] = None
    changelog: Optional[str] = None


@dataclass
class ScraperResult:
    """Result from a scraping operation."""
    success: bool
    devices: List[ScrapedDevice] = field(default_factory=list)
    firmware_versions: List[ScrapedFirmware] = field(default_factory=list)
    error: Optional[str] = None

    # The scraper deliberately did not look this run. Distinct from an empty success,
    # which asserts the vendor publishes nothing: this asserts nothing at all, and
    # lands in `devices_not_checked` beside the devices a budget overrun skipped.
    # Set by scrapers that spread their catalogue over several runs -- see korg.py,
    # where checking all 164 products in one run exceeds the hard timeout.
    not_checked: bool = False


logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Abstract base class for manufacturer scrapers."""

    # Override in subclass
    manufacturer_name: str = ""
    manufacturer_slug: str = ""
    manufacturer_website: str = ""

    def __init__(self):
        self.settings = get_settings()
        self._last_request_time: Optional[float] = None
        # url -> fingerprint of what it returned. Read after a scrape to catch a URL
        # shape that has stopped selecting anything; see identical_pages().
        self._page_fingerprints: Dict[str, str] = {}
        # "url: reason" for every fetch that broke outright this run -- a timeout, a
        # dropped connection, a 5xx. Read by the service after a scrape; see
        # fetch_failures().
        self._fetch_failures: List[str] = []
        self._session: Optional[aiohttp.ClientSession] = None
        self._playwright = None
        self._browser: Optional["Browser"] = None
        self._resolver: Optional[netguard.GuardedResolver] = None
        # host -> may a rendered page load from it. Per scraper, so per run.
        self._host_verdicts: Dict[str, bool] = {}
        # The store backs two different behaviours, so it exists if either is on.
        # _serve_from_cache is the development one that skips the network entirely;
        # _revalidate is the production one that still fetches, but conditionally.
        # Keeping them separate matters: if a stale body could be served whenever the
        # store exists, enabling revalidation would silently stop finding new firmware.
        self._serve_from_cache = self.settings.scrape_cache
        self._revalidate = self.settings.http_revalidate
        self._cache: Optional[ResponseCache] = (
            ResponseCache(
                self.settings.scrape_cache_dir,
                self.settings.scrape_cache_ttl_hours * 3600,
            )
            if (self._serve_from_cache or self._revalidate)
            else None
        )

    @property
    def scraper_type(self) -> str:
        """Returns the scraper type identifier (used for registry lookup)."""
        return self.manufacturer_slug

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.settings.request_timeout)
            # Every connection is checked against where it actually lands, and every
            # request -- redirect hops included -- against an IP literal it names.
            # See netguard.py for why both are needed.
            self._resolver = netguard.GuardedResolver()
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=aiohttp.TCPConnector(resolver=self._resolver),
                middlewares=(netguard.refuse_literal_addresses,),
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                },
            )
        return self._session

    def _fingerprint(self, url: str, body: Optional[str]) -> None:
        """Remember what a URL returned, so identical answers can be spotted later.

        Hashes the visible text with scripts and styles removed, not the raw HTML.
        Elektron's pages are identical in every way that matters and differ by a
        single injected value -- `window.__wc_fb_page_generated = 1789238504` -- which
        changes per request and is the same length every time. Hashing the body makes
        eleven copies of one page look like eleven different pages, which is precisely
        the case this exists to catch.
        """
        if not body:
            return
        try:
            soup = self.parse_html(body)
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
        except Exception:
            # A fingerprint is diagnostic, so failing to take one must not affect
            # the fetch that produced it.
            return
        self._page_fingerprints[url] = hashlib.sha256(
            text.encode("utf-8", "replace")
        ).hexdigest()

    def identical_pages(self) -> List[List[str]]:
        """Groups of different URLs that returned exactly the same thing.

        Every dead-URL case in this project has this shape. Yamaha's eleven product
        pages and a slug invented to test them all returned the same landing page.
        Elektron's `?connection=<product>` URLs returned one byte-identical page for
        every product, and the versions reported for eleven instruments came off a
        news blurb on it. Boss's two Katana URLs matched a control. Line 6 served
        three category pages at exactly 1,778 characters each.

        Several products legitimately share one URL -- QSC's K.2 range, every Peterson
        product, all of Steinberg -- and that is a single URL rather than several, so
        it does not appear here. What appears is a URL shape that has stopped
        selecting anything, which otherwise reads as "these products publish no
        firmware".
        """
        by_fingerprint: Dict[str, List[str]] = {}
        for url, fingerprint in self._page_fingerprints.items():
            by_fingerprint.setdefault(fingerprint, []).append(url)
        return [sorted(urls) for urls in by_fingerprint.values() if len(urls) > 1]

    def _record_fetch_failure(self, url: str, reason: str) -> None:
        self._fetch_failures.append(f"{url}: {reason}")

    def fetch_failures(self) -> List[str]:
        """Fetches that broke outright this run, as "url: reason".

        A scraper that skips a product whose page did not load reports success with
        that product absent, and nothing in its result says so: Korg's Pa4X page takes
        31s against the 30s limit and was missing from every sweep that read "ok".
        404s are not recorded -- scrapers probe URLs that are allowed to be missing, and
        counting them would bury the pages that should have loaded.
        """
        return list(self._fetch_failures)

    async def _rate_limit(self):
        """Enforce rate limiting between requests."""
        if self._last_request_time is not None:
            elapsed = asyncio.get_event_loop().time() - self._last_request_time
            if elapsed < self.settings.rate_limit_delay:
                await asyncio.sleep(self.settings.rate_limit_delay - elapsed)
        self._last_request_time = asyncio.get_event_loop().time()

    async def fetch_page(self, url: str, timeout: Optional[float] = None) -> Optional[str]:
        """Fetch a page with rate limiting (static HTML only).

        `timeout` overrides the session's `request_timeout` for this request, for the
        vendor page that is reliably slower than the rest rather than broken.
        """
        if self._serve_from_cache and self._cache:
            cached = self._cache.get("GET", url)
            if cached is not None:
                # Fingerprinted here too, or a cached debugging run reports no
                # duplicates and the check silently stops working while enabled.
                self._fingerprint(url, cached)
                return cached

        stored = self._cache.entry("GET", url) if self._cache else None
        headers = (
            ResponseCache.conditional_headers(stored) if self._revalidate else {}
        )

        logger.debug("GET %s%s", url, " (conditional)" if headers else "")
        await self._rate_limit()
        session = await self._get_session()
        request_options = {"timeout": aiohttp.ClientTimeout(total=timeout)} if timeout else {}
        try:
            async with session.get(url, headers=headers, **request_options) as response:
                # 304: the page is unchanged and carries no body, so reuse the one
                # we already have. Only reachable when a validator was sent, and
                # conditional_headers only sends one when a body exists.
                if response.status == 304 and stored and stored.get("body"):
                    logger.debug("304 unchanged, reusing stored body for %s", url)
                    self._cache.touch("GET", url)
                    self._fingerprint(url, stored["body"])
                    return stored["body"]
                if response.status == 200:
                    body = await netguard.read_text_capped(
                        response, self.settings.max_response_bytes
                    )
                    self._fingerprint(url, body)
                    if self._cache:
                        self._cache.set(
                            "GET",
                            url,
                            body,
                            etag=response.headers.get("ETag"),
                            last_modified=response.headers.get("Last-Modified"),
                        )
                    return body
                if response.status >= 500:
                    self._record_fetch_failure(url, f"HTTP {response.status}")
                return None
        except Exception as e:
            logger.warning("Fetch failed for %s: %s", url, str(e) or type(e).__name__)
            self._record_fetch_failure(url, type(e).__name__)
            return None

    async def fetch_json(
        self, url: str, method: str = "GET", json_body: Optional[dict] = None, **kwargs
    ) -> Optional[dict]:
        """Fetch and decode JSON, through the same cache as fetch_page.

        Scrapers that read an API were reaching for the session directly and so sat
        outside the cache entirely. The request body is part of the cache key,
        because Modartt picks a product with one.
        """
        body_repr = json.dumps(json_body, sort_keys=True) if json_body else None
        if self._serve_from_cache and self._cache:
            cached = self._cache.get(method, url, body_repr)
            if cached is not None:
                try:
                    return json.loads(cached)
                except ValueError:
                    pass  # fall through and refetch

        stored = self._cache.entry(method, url, body_repr) if self._cache else None
        headers = dict(kwargs.pop("headers", None) or {})
        if self._revalidate:
            headers.update(ResponseCache.conditional_headers(stored))

        logger.debug("%s %s", method, url)
        await self._rate_limit()
        session = await self._get_session()
        try:
            async with session.request(
                method, url, json=json_body, headers=headers, **kwargs
            ) as response:
                if response.status == 304 and stored and stored.get("body"):
                    self._cache.touch(method, url, body_repr)
                    try:
                        return json.loads(stored["body"])
                    except ValueError:
                        return None
                if response.status != 200:
                    if response.status >= 500:
                        self._record_fetch_failure(url, f"HTTP {response.status}")
                    return None
                text = await netguard.read_text_capped(
                    response, self.settings.max_response_bytes
                )
                etag = response.headers.get("ETag")
                last_modified = response.headers.get("Last-Modified")
        except Exception as e:
            logger.warning("Fetch failed for %s: %s", url, str(e) or type(e).__name__)
            self._record_fetch_failure(url, type(e).__name__)
            return None

        try:
            data = json.loads(text)
        except ValueError:
            return None

        if self._cache:
            self._cache.set(
                method, url, text, body_repr, etag=etag, last_modified=last_modified
            )
        return data

    async def _get_browser(self) -> "Browser":
        """Get or create a Playwright browser instance."""
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("Playwright is not installed. Run: pip install playwright && playwright install chromium")
        if self._browser is None or not self._browser.is_connected():
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
        return self._browser

    async def fetch_page_js(
        self,
        url: str,
        wait_for_selector: Optional[str] = None,
        click_selector: Optional[str] = None,
        wait_for_timeout: int = 5000,
    ) -> Optional[str]:
        """
        Fetch a page that requires JavaScript rendering.

        Args:
            url: The URL to fetch
            wait_for_selector: CSS selector to wait for before capturing HTML
            click_selector: CSS selector to click before capturing (e.g., tab buttons)
            wait_for_timeout: Max time in ms to wait for the page to load

        Returns:
            The fully rendered HTML content, or None on error
        """
        # The selectors are part of the key: clicking a tab changes what the page
        # renders, so the same URL fetched with a different click_selector is a
        # different response, not a repeat of the same one.
        variant = json.dumps(
            {"click": click_selector, "wait": wait_for_selector}, sort_keys=True
        )
        # No revalidation branch here: a Playwright navigation has no practical way
        # to send If-None-Match and act on a 304, so rendered pages are only ever
        # served from the development cache.
        if self._serve_from_cache and self._cache:
            cached = self._cache.get("GET-JS", url, variant)
            if cached is not None:
                self._fingerprint(url, cached)
                # Returning before _get_browser also skips launching Chromium, which
                # is most of what makes a cached debug run fast.
                return cached

        logger.debug("GET (rendered) %s", url)
        await self._rate_limit()
        try:
            browser = await self._get_browser()
            # A context rather than a bare page. Routing installed on a page never sees
            # what a popup requests, and service workers can only be turned off where
            # the context is made. Both were measured against this project's Chromium:
            # a page opened an unguarded window on load -- no click needed -- and a
            # service worker fetched from inside its own install handler. Four requests
            # reached a local target that the page-level guard never saw.
            context = await browser.new_context(service_workers="block")
            try:
                # Before navigating, so the page itself is checked as well as
                # everything its scripts go on to request -- and on the context, so it
                # covers every page opened in it rather than only the first.
                await context.route("**/*", self._guard_browser_request)
                page = await context.new_page()

                # A window the page opens is left open until the context closes below.
                # Closing each one as it appeared was tried first and is worse:
                # Playwright attaches a context's routes to a new page asynchronously,
                # so racing that with close() intermittently let the popup's own
                # fetches out unintercepted -- the exact hole this is here to shut.
                # Measured both ways against this project's Chromium: left alone, the
                # popup's navigation *and* every request its scripts make go through
                # the guard; closed eagerly, a second popup got far enough to fetch
                # before it died. context.close() in the finally disposes of them all,
                # so nothing outlives the fetch either way.
                # Use domcontentloaded instead of networkidle to avoid
                # hanging on pages with long-polling or streaming connections.
                # A navigation timeout is tried once more: TAL's pages were slow for a
                # few minutes and fine after, and failed a whole sweep over it. Only a
                # timeout -- a refused or blocked navigation will not change on retry.
                response = None
                for attempt in (1, 2):
                    try:
                        response = await page.goto(
                            url, wait_until="domcontentloaded", timeout=wait_for_timeout
                        )
                        break
                    except Exception as exc:
                        if attempt == 2 or type(exc).__name__ != "TimeoutError":
                            raise
                        logger.info("Rendered fetch of %s timed out, trying once more", url)

                # The route guard above never sees where a redirect went, so the
                # navigation's own chain is checked before anything is read off the
                # page. See _navigation_chain_allowed.
                if not await self._navigation_chain_allowed(response):
                    return None

                # Click element if specified (e.g., to expand a tab or section)
                if click_selector:
                    try:
                        element = await page.wait_for_selector(click_selector, timeout=3000)
                        if element:
                            await element.click()
                            await page.wait_for_timeout(1500)
                    except Exception:
                        pass  # Continue even if click fails

                if wait_for_selector:
                    await page.wait_for_selector(wait_for_selector, timeout=wait_for_timeout)
                else:
                    await page.wait_for_timeout(1000)
                html = await self._content_within_cap(page, url)
                self._fingerprint(url, html)
                if self._cache and html:
                    self._cache.set("GET-JS", url, html, variant)
                return html
            finally:
                await context.close()
        except Exception as e:
            logger.warning("Rendered fetch failed for %s: %s", url, e)
            self._record_fetch_failure(url, type(e).__name__)
            return None

    async def _content_within_cap(self, page, url: str) -> str:
        """The rendered DOM, refused if it is over `max_response_bytes`.

        The aiohttp paths cap a body while it streams, so an oversized page is dropped
        before it is ever held whole -- see `netguard.read_text_capped`, and the note
        there that a small gzip can expand to gigabytes. A rendered page has no stream
        to watch: by the time `page.content()` returns, a string the size of the
        document already exists in this process, which is the memory the cap is for.
        So the length is asked for inside the browser first, and the serialisation is
        only pulled across when it fits.

        That first measurement is best-effort. `evaluate` can fail on a page whose
        context has gone, and it is deliberately allowed to: the byte check below is
        what actually guarantees the cap. It counts UTF-8 bytes because that is what
        the aiohttp path counts, and because `.length` in the browser counts UTF-16
        code units -- a page of CJK text measures about a third of its real size
        there, and would otherwise pass a check it should fail.

        Raises `netguard.ResponseTooLarge`, which `fetch_page_js` already turns into a
        recorded fetch failure, so an oversized rendered page reports the same reason
        as an oversized fetched one.
        """
        limit = self.settings.max_response_bytes
        try:
            measured = await page.evaluate("document.documentElement.outerHTML.length")
        except Exception:
            measured = None
        if isinstance(measured, (int, float)) and measured > limit:
            raise netguard.ResponseTooLarge(
                f"{url} renders {int(measured)} characters, over the {limit}-byte cap"
            )

        html = await page.content()
        size = len(html.encode("utf-8", "replace"))
        if size > limit:
            raise netguard.ResponseTooLarge(
                f"{url} rendered {size} bytes, over the {limit}-byte cap"
            )
        return html

    async def _guard_browser_request(self, route) -> None:
        """Let a rendered page load only what lives on the public internet.

        A page's own scripts decide what else Chromium fetches, so the address check
        that covers aiohttp is repeated here for every request the browser makes.
        """
        url = route.request.url
        if await netguard.url_allowed(url, self._host_verdicts):
            await route.continue_()
        else:
            logger.warning("Blocked rendered request to a non-public address: %s", url)
            await route.abort("blockedbyclient")

    async def _navigation_chain_allowed(self, response) -> bool:
        """Check every hop of a navigation, not only the URL that was asked for.

        `page.route` is not consulted for the target of a redirect Chromium follows.
        The handler fires once, for the URL the navigation started at, and the
        `Location` it is sent to is fetched and rendered without ever reaching
        `netguard.url_allowed`. Measured against this project's own Chromium: a page
        answering 302 had the target requested, served, and returned by
        `page.content()`, while the route handler recorded only the first URL.

        That is the whole difference between this path and the aiohttp one. There a
        client middleware runs per hop, so a redirect into the network is refused
        before the connection is made. Here the request has already happened by the
        time anything can look, so what this refuses is the *content*: the body is
        discarded and the caller told nothing loaded, which keeps a credential
        response out of the database and off the public catalogue. The request itself
        still went out; egress rules are the layer that covers that.

        Prevention was tried and rejected on measurement. Following the chain inside
        the route handler with `route.fetch(max_redirects=0)` and fulfilling the final
        response does validate every hop -- but Chromium then never learns the final
        URL, and relative sub-resources resolve against the original one: a page
        redirected to `/sub/b` requested `/img.png` rather than `/sub/img.png`. Keeping
        the base URL right as well would mean fetching every rendered page twice, and
        doubling the load on vendors is not a trade this project makes for a risk that
        discarding the body already covers.
        """
        if response is None:
            return True

        request = getattr(response, "request", None)
        hops = []
        while request is not None:
            hops.append(request.url)
            request = getattr(request, "redirected_from", None)

        for hop in hops:
            if not await netguard.url_allowed(hop, self._host_verdicts):
                logger.warning(
                    "Blocked a rendered redirect into a non-public address: %s", hop
                )
                self._record_fetch_failure(hop, "BlockedRedirect")
                return False
        return True

    def parse_html(self, html: str) -> BeautifulSoup:
        """Parse HTML content."""
        return BeautifulSoup(html, "lxml")

    async def close(self):
        """Close the aiohttp session and Playwright browser."""
        if self._session and not self._session.closed:
            await self._session.close()
        # The connector does not own a resolver it was handed, so it is closed here.
        resolver = getattr(self, "_resolver", None)
        if resolver is not None:
            await resolver.close()
            self._resolver = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    @abstractmethod
    async def fetch_device_list(self) -> ScraperResult:
        """
        Fetch the list of devices from the manufacturer.
        Returns a ScraperResult with devices populated.
        """
        pass

    @abstractmethod
    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        """
        Fetch firmware versions for a specific device.
        Returns a ScraperResult with firmware_versions populated.
        """
        pass

    async def fetch_changelog(
        self, firmware_version: str, changelog_url: str
    ) -> Optional[str]:
        """
        Fetch the full changelog text for a specific firmware version.
        Default implementation returns None - override if changelog is on separate page.
        """
        return None

    async def scrape_all(self) -> ScraperResult:
        """
        Full scrape: fetch devices, then firmware for each.
        Override if manufacturer has a different scraping pattern.
        """
        try:
            devices_result = await self.fetch_device_list()
            if not devices_result.success:
                return devices_result

            all_firmware = []
            for device in devices_result.devices:
                if device.firmware_page_url:
                    fw_result = await self.fetch_firmware_versions(
                        device.name, device.firmware_page_url
                    )
                    if fw_result.success:
                        all_firmware.extend(fw_result.firmware_versions)

            return ScraperResult(
                success=True,
                devices=devices_result.devices,
                firmware_versions=all_firmware,
            )
        except Exception as e:
            return ScraperResult(success=False, error=str(e))
        finally:
            await self.close()
