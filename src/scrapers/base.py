from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
import asyncio
import aiohttp
from bs4 import BeautifulSoup

from src.config import get_settings


@dataclass
class ScrapedDevice:
    """Represents a device discovered by a scraper."""
    name: str
    category: str
    firmware_page_url: Optional[str] = None
    product_url: Optional[str] = None


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


class BaseScraper(ABC):
    """Abstract base class for manufacturer scrapers."""

    # Override in subclass
    manufacturer_name: str = ""
    manufacturer_slug: str = ""
    manufacturer_website: str = ""

    def __init__(self):
        self.settings = get_settings()
        self._last_request_time: Optional[float] = None
        self._session: Optional[aiohttp.ClientSession] = None

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

    async def _rate_limit(self):
        """Enforce rate limiting between requests."""
        if self._last_request_time is not None:
            elapsed = asyncio.get_event_loop().time() - self._last_request_time
            if elapsed < self.settings.rate_limit_delay:
                await asyncio.sleep(self.settings.rate_limit_delay - elapsed)
        self._last_request_time = asyncio.get_event_loop().time()

    async def fetch_page(self, url: str) -> Optional[str]:
        """Fetch a page with rate limiting."""
        await self._rate_limit()
        session = await self._get_session()
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.text()
                return None
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            return None

    def parse_html(self, html: str) -> BeautifulSoup:
        """Parse HTML content."""
        return BeautifulSoup(html, "lxml")

    async def close(self):
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()

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
