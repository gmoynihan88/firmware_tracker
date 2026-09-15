import logging
import re
from typing import Dict, List, Optional, Tuple

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class HeadRushScraper(BaseScraper):
    """HeadRush -- every current and archived firmware updater on its downloads page.

    `downloads.html` is one page with a section per product, headed by the product's
    name, listing its firmware updaters -- the current release first, older ones below
    in blocks of their own -- beside instructions, user guides and drivers:

        <a href="/products/core/index.html"><h4>Core</h4></a>
        <!-- Core Firmware v5.1.0) -->
        <div class="row"><div class="col">HeadRush Core 5.1.0 Firmware Updater (Mac)</div>...
        <div class="row"><div class="col">HeadRush Core - User Guide 5.1.0</div>...

    **No date is published**, checked 2026-09-14; the CDN paths carry a version folder
    (`/SGEE/51/`), not a date. Every release is stored undated.

    **Only an updater is a release.** User guides, instructions and drivers carry
    versions too -- "HeadRush Core - User Guide 5.1.0", "HeadRush VX5 AutoTune - 1.0.0 PC
    Networking Driver" -- so a row is read only when it names a Firmware Updater. The
    label is written two ways: "HeadRush Core 5.1.0 Firmware Updater (Mac)" and
    "HeadRush MX5 - Firmware Updater v2.7.0 (Mac)".

    **VX5 AutoTune has no updater on the page**, only "HeadRush VX5 AutoTune - Firmware
    Update 1.3.1 Instructions" (it updates through the HeadRush app). Where a product
    has no updater at all, its firmware-update instructions state the version; the
    driver beside them does not.

    **Only what the page shows is read.** MX5, Pedalboard and Gigboard's older updaters
    (v2.6.0) sit inside HTML comments on the live page; the vendor has not published
    them, so they are not read. Core, Prime and Flex Prime's older updaters are live
    rows and are.

    **The FRFR speakers publish no firmware** and are not listed. Mac and Windows
    updaters of one version are one release, linked to whichever the page lists first.
    """

    manufacturer_name = "HeadRush"
    manufacturer_slug = "headrush"
    manufacturer_website = "https://www.headrushfx.com"

    DOWNLOADS_URL = "https://www.headrushfx.com/downloads.html"
    UPDATER = re.compile(
        r"(?:\bv?(?P<before>\d+(?:\.\d+)+)\s+Firmware\s+Updater|Firmware\s+Updater\s+v?(?P<after>\d+(?:\.\d+)+))", re.I)
    INSTRUCTIONS = re.compile(
        r"Firmware\s+Update\s+(?:Instructions\s+)?v?(?P<version>\d+(?:\.\d+)+)(?:\s+Instructions)?", re.I)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._devices: Optional[Dict[str, List[ScrapedFirmware]]] = None

    # --- parsing ------------------------------------------------------------

    @staticmethod
    def _numbers(version: str) -> Tuple[int, ...]:
        return tuple(int(n) for n in version.split("."))

    def _parse_page(self, html: str) -> Dict[str, List[ScrapedFirmware]]:
        soup = self.parse_html(html)
        products: Dict[str, List[ScrapedFirmware]] = {}
        for heading in soup.find_all("h4"):
            name = " ".join(heading.get_text(" ").split())
            section = heading.find_parent(lambda tag: tag.name == "div" and len(tag.find_all("h4")) == 1)
            if not name or section is None:
                continue
            rows = []
            for row in section.select("div.row"):
                columns = row.select("div.col")
                if columns:
                    link = row.find("a", href=True)
                    rows.append((" ".join(columns[0].get_text(" ").split()), link["href"] if link else None))

            releases: Dict[str, Tuple[str, Optional[str]]] = {}
            for label, href in rows:
                matched = self.UPDATER.search(label)
                if matched:
                    releases.setdefault(matched.group("before") or matched.group("after"), (label, href))
            if not releases:
                for label, _href in rows:
                    matched = self.INSTRUCTIONS.search(label)
                    if matched:
                        releases.setdefault(matched.group("version"), (label, None))
            if not releases:
                continue

            branded = name if name.lower().startswith("headrush") else f"HeadRush {name}"
            products[branded] = [
                ScrapedFirmware(version=version, release_date=None, download_url=href, changelog=label)
                for version, (label, href) in sorted(releases.items(), key=lambda kv: self._numbers(kv[0]), reverse=True)
            ]
        return products

    # --- loading ------------------------------------------------------------

    async def _load(self) -> Optional[Dict[str, List[ScrapedFirmware]]]:
        if self._devices is None:
            html = await self.fetch_page(self.DOWNLOADS_URL)
            self._devices = (self._parse_page(html) if html else {}) or None
        return self._devices

    async def fetch_device_list(self) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error=f"No HeadRush firmware updaters found at {self.DOWNLOADS_URL}")
        return ScraperResult(
            success=True,
            devices=[ScrapedDevice(name=name, category="guitar_pedal", firmware_page_url=self.DOWNLOADS_URL,
                                   product_url=self.DOWNLOADS_URL) for name in devices],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error=f"No HeadRush firmware updaters found at {self.DOWNLOADS_URL}")
        return ScraperResult(success=True, firmware_versions=list(devices.get(device_name, [])))
