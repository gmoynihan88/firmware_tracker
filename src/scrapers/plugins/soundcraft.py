import asyncio
import re
from typing import Dict, List, Optional
from urllib.parse import urljoin

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class SoundcraftScraper(BaseScraper):
    """Soundcraft consoles, from the two download tables on soundcraft.com.

    Two pages, one table each, both listing a "Latest Version" column and the products
    every row is for:

        /en-US/firmware   Ui12 Firmware Update | 1.0.7548 | Ui12
        /en-US/software   Si Impact Console Software v2.2 build 1 | 2.2 build 1 | Si Impact

    **The firmware page is all firmware.** The Ui24R has three rows (3.0, 3.3, 3.5),
    which are its releases; Notepad's firmware ships with its control panel and the two
    platform rows carry one version.

    **The software page is mostly not.** It lists offline editors (Si Offline Impact,
    Vi3000 Offline Editor), USB drivers, the Soundcraft Control Panel, Virtual Vi, the
    Connected PA and ViSi apps, and a downgrader, each versioned on its own track. Only
    console software and console updaters are read:

        Si Impact Console Software v2.2 build 1        Si Impact
        Si Performer Console Software v2.2 build 1     Si Performer 1, 2, 3
        Si Expression Console Updater v2.2 build 1     Si Expression 1, 2, 3
        Update_Console.7z v6.4.8.360                   the Vi range
        Vix000_Vix00_Vi1-6_Update_updater.zip v5.0.0.39
        [PREVIOUS] Vi3000 Software Update v5.0.1.253   Vi3000

    **A row's products are its Related Products links**, so a console appears once with
    every version its rows carry. "Vi400/600 Upgrade" is an upgrade kit rather than a
    console and is left out.

    **Versions are as written**, "2.2 build 1" included. Nothing here is dated: the
    tables have no date column, and the pages carry only a "Last Updated" stamp of
    their own.

    robots.txt asks ClaudeBot and anthropic-ai for ten seconds between requests, which
    `_rate_limit` honours; this scraper makes two requests.
    """

    manufacturer_name = "Soundcraft"
    manufacturer_slug = "soundcraft"
    manufacturer_website = "https://www.soundcraft.com"

    FIRMWARE_URL = "https://www.soundcraft.com/en-US/firmware"
    SOFTWARE_URL = "https://www.soundcraft.com/en-US/software"

    # robots.txt: "User-agent: ClaudeBot / Crawl-delay: 10".
    CRAWL_DELAY = 10.0

    CONSOLE_SOFTWARE = re.compile(r"console\s+(?:software|updater)|update_console|_update_updater|software\s+update", re.I)
    NOT_CONSOLE = re.compile(r"offline|virtual|driver|downgrader|editor|control\s+panel|app\b", re.I)
    NOT_A_CONSOLE_PRODUCT = re.compile(r"upgrade|option\s+cards", re.I)
    VERSION = re.compile(r"^v?(?P<version>\d+(?:\.\d+)+(?:\s+build\s+\d+)?)$", re.I)
    # "Ui24R Firmware Update" -- the console a row is for, when it lists no product.
    ROW_MODEL = re.compile(r"^(?P<model>[A-Za-z][\w+.-]*)\s+Firmware\b")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._catalogue: Optional[Dict[str, dict]] = None

    async def _rate_limit(self):
        """Ten seconds between requests, as Soundcraft's robots.txt asks of us."""
        loop = asyncio.get_event_loop()
        if self._last_request_time is not None:
            elapsed = loop.time() - self._last_request_time
            if elapsed < self.CRAWL_DELAY:
                await asyncio.sleep(self.CRAWL_DELAY - elapsed)
        self._last_request_time = loop.time()

    @staticmethod
    def _text(element) -> str:
        return " ".join(element.get_text(" ", strip=True).split())

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(part) for part in re.findall(r"\d+", version))

    def _rows(self, html: str, console_only: bool) -> List[dict]:
        """(name, version, products, url) for each table row that names a version."""
        rows: List[dict] = []
        for row in self.parse_html(html).find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) < 3:
                continue
            name = self._text(cells[0])
            matched = self.VERSION.match(self._text(cells[1]))
            if not name or not matched:
                continue
            if console_only and (not self.CONSOLE_SOFTWARE.search(name) or self.NOT_CONSOLE.search(name)):
                continue
            products = [
                self._text(link) for link in cells[-1].find_all("a", href=True)
                if self._text(link) and not self.NOT_A_CONSOLE_PRODUCT.search(self._text(link))
            ]
            if not products:
                # The Ui24R's third firmware row lists no related product, and dropping
                # it loses that release. The row names the console it is for.
                named = self.ROW_MODEL.match(name)
                products = [named.group("model")] if named else []
            link = cells[0].find("a", href=True)
            rows.append({
                "name": name,
                "version": matched.group("version"),
                "products": products,
                "url": urljoin(self.manufacturer_website, link["href"]) if link else None,
            })
        return rows

    async def _load(self) -> Optional[Dict[str, dict]]:
        if self._catalogue is not None:
            return self._catalogue

        found: Dict[str, dict] = {}
        for url, console_only in ((self.FIRMWARE_URL, False), (self.SOFTWARE_URL, True)):
            html = await self.fetch_page(url)
            if not html:
                # One page carries the Ui and Notepad firmware and the other the
                # consoles'; losing either would drop its products silently.
                return None
            for row in self._rows(html, console_only):
                for product in row["products"]:
                    entry = found.setdefault(product, {"url": row["url"] or url, "versions": {}})
                    entry["versions"].setdefault(row["version"], ScrapedFirmware(version=row["version"], download_url=row["url"]))

        catalogue = {
            product: {
                "url": entry["url"],
                "versions": sorted(entry["versions"].values(), key=lambda fw: self._version_key(fw.version), reverse=True),
            }
            for product, entry in found.items()
        }
        if not catalogue:
            return None
        self._catalogue = catalogue
        return catalogue

    async def fetch_device_list(self) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(success=False, error=f"Could not read Soundcraft's downloads from {self.FIRMWARE_URL}")
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    # Mixing consoles: none of the other categories fits.
                    name=name,
                    category="other",
                    firmware_page_url=entry["url"],
                    product_url=entry["url"],
                )
                for name, entry in catalogue.items()
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(success=False, error=f"Could not read Soundcraft's downloads from {self.FIRMWARE_URL}")
        entry = catalogue.get(device_name)
        if entry is None:
            return ScraperResult(success=False, error=f"{device_name} has no firmware row on Soundcraft's downloads pages")
        return ScraperResult(success=True, firmware_versions=entry["versions"])
