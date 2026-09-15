import logging
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class SeratoScraper(BaseScraper):
    """Serato -- DJ Pro, DJ Lite, Studio, Sample and Hex FX, the version each downloads page leads with.

    serato.com's home page links a downloads page per product, and each opens with its
    current release and what it changed:

        <h1>Download Serato DJ Pro</h1>
        <h2>What's New in 4.0.9</h2><h3>AlphaTheta XDJ-AN Support</h3><p>...</p>

    **Only the current version is published, and it is undated**, checked 2026-09-14.
    The downloads pages link no older releases, and support.serato.com's help centre
    holds no release-notes articles -- a search for them returns operating-system
    compatibility and how-to pages. Its "Hardware Drivers and Firmware" articles are for
    Novation, Numark, Reloop and other makers' controllers, not Serato's own. So each
    product carries one version, stored without a date, and gains history only as this
    tracker sees new releases.

    **The heading is written two ways**: "What's New in 4.0.9" on DJ Pro and DJ Lite,
    "What's New in Studio 2.5.0" on Studio and Sample. The apostrophe is typographic.

    Product pages are discovered from the home page's links rather than listed here, so
    a new product's downloads page is picked up when Serato links it.
    """

    manufacturer_name = "Serato"
    manufacturer_slug = "serato"
    manufacturer_website = "https://serato.com"

    BASE_URL = "https://serato.com"
    DOWNLOADS_PAGE = re.compile(r"^(?:https?://(?:www\.)?serato\.com)?(/[a-z0-9-]+(?:/[a-z0-9-]+)?/downloads)/?$")
    WHATS_NEW = re.compile(r"^What.s\s+New\s+in\s+(?:.*?\s)?v?(?P<version>\d+(?:\.\d+)+)$", re.I)
    NOTES_LIMIT = 4000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._devices: Optional[Dict[str, Tuple[str, ScrapedFirmware]]] = None

    # --- parsing ------------------------------------------------------------

    def _parse_home(self, html: str) -> List[str]:
        urls: List[str] = []
        for link in self.parse_html(html).find_all("a", href=True):
            matched = self.DOWNLOADS_PAGE.match(link["href"].split("#")[0].split("?")[0])
            if matched:
                url = urljoin(self.BASE_URL, matched.group(1))
                if url not in urls:
                    urls.append(url)
        return urls

    def _parse_page(self, html: str) -> Optional[Tuple[str, ScrapedFirmware]]:
        soup = self.parse_html(html)
        heading = soup.find("h1")
        name = re.sub(r"^Download\s+", "", " ".join(heading.get_text(" ").split()), flags=re.I) if heading else ""
        if not name:
            return None
        for title in soup.find_all("h2"):
            matched = self.WHATS_NEW.match(" ".join(title.get_text(" ").split()))
            if not matched:
                continue
            notes: List[str] = []
            for sibling in title.find_next_siblings():
                if sibling.name in ("h1", "h2"):
                    break
                line = " ".join(sibling.get_text(" ").split())
                if line:
                    notes.append(line)
            return name, ScrapedFirmware(version=matched.group("version"), release_date=None,
                                         changelog="\n".join(notes)[: self.NOTES_LIMIT] or None)
        return None

    # --- loading ------------------------------------------------------------

    async def _load(self) -> Optional[Dict[str, Tuple[str, ScrapedFirmware]]]:
        if self._devices is not None:
            return self._devices
        home = await self.fetch_page(self.BASE_URL + "/")
        pages = self._parse_home(home) if home else []
        devices: Dict[str, Tuple[str, ScrapedFirmware]] = {}
        for url in pages:
            html = await self.fetch_page(url)
            parsed = self._parse_page(html) if html else None
            if parsed is None:
                logger.warning("Serato downloads page %s did not load or named no current version", url)
                continue
            devices.setdefault(parsed[0], (url, parsed[1]))
        self._devices = devices or None
        return self._devices

    async def fetch_device_list(self) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error="No Serato downloads page named a current version")
        return ScraperResult(
            success=True,
            devices=[ScrapedDevice(name=name, category="vst_plugin", firmware_page_url=url, product_url=url)
                     for name, (url, _firmware) in devices.items()],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error="No Serato downloads page named a current version")
        entry = devices.get(device_name)
        return ScraperResult(success=True, firmware_versions=[entry[1]] if entry else [])
