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
        self._session: Optional[aiohttp.ClientSession] = None
        self._playwright = None
        self._browser: Optional["Browser"] = None
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
            self._session = aiohttp.ClientSession(
                timeout=timeout,
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

    async def _rate_limit(self):
        """Enforce rate limiting between requests."""
        if self._last_request_time is not None:
            elapsed = asyncio.get_event_loop().time() - self._last_request_time
            if elapsed < self.settings.rate_limit_delay:
                await asyncio.sleep(self.settings.rate_limit_delay - elapsed)
        self._last_request_time = asyncio.get_event_loop().time()

    async def fetch_page(self, url: str) -> Optional[str]:
        """Fetch a page with rate limiting (static HTML only)."""
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
        try:
            async with session.get(url, headers=headers) as response:
                # 304: the page is unchanged and carries no body, so reuse the one
                # we already have. Only reachable when a validator was sent, and
                # conditional_headers only sends one when a body exists.
                if response.status == 304 and stored and stored.get("body"):
                    logger.debug("304 unchanged, reusing stored body for %s", url)
                    self._cache.touch("GET", url)
                    self._fingerprint(url, stored["body"])
                    return stored["body"]
                if response.status == 200:
                    body = await response.text()
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
                return None
        except Exception as e:
            logger.warning("Fetch failed for %s: %s", url, e)
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
                    return None
                text = await response.text()
                etag = response.headers.get("ETag")
                last_modified = response.headers.get("Last-Modified")
        except Exception as e:
            logger.warning("Fetch failed for %s: %s", url, e)
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
            page = await browser.new_page()
            try:
                # Use domcontentloaded instead of networkidle to avoid
                # hanging on pages with long-polling or streaming connections
                await page.goto(url, wait_until="domcontentloaded", timeout=wait_for_timeout)

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
                html = await page.content()
                self._fingerprint(url, html)
                if self._cache and html:
                    self._cache.set("GET-JS", url, html, variant)
                return html
            finally:
                await page.close()
        except Exception as e:
            logger.warning("Rendered fetch failed for %s: %s", url, e)
            return None

    def parse_html(self, html: str) -> BeautifulSoup:
        """Parse HTML content."""
        return BeautifulSoup(html, "lxml")

    async def close(self):
        """Close the aiohttp session and Playwright browser."""
        if self._session and not self._session.closed:
            await self._session.close()
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
