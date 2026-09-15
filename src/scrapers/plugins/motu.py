import json
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)

MONTHS = {name: number for number, name in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


class MOTUScraper(BaseScraper):
    """MOTU -- Digital Performer, Performer Lite, AudioDesk and its instruments; not its hardware.

    motu.com's download centre lists products by category through a JSON endpoint its
    page calls, and each product's download page tabulates its installers:

        GET /en-us/download/filters/?category=5
        {"products": [{"id": 489, "title": "Digital Performer 11"}, ...]}

        <thead><tr><th><b>Installer</b></th>...</thead>
        <tbody><tr><td><b>Digital Performer 11</b>
          <span class="vnum">Mac v11.36+101486</span><span class="vnum"> | Jan. 29, 2026</span>

    Categories 5 (Audio Software) and 6 (Virtual Instruments) are read. Each page gives
    the current installer only -- "View all Downloads" shows the same rows -- so each
    product carries one version, dated.

    **Hardware is not read, because MOTU publishes no firmware version**, checked
    2026-09-14. Interface pages offer driver installers whose Mac and Windows builds
    number differently ("MOTU M-Series Installer Mac v2.0.2+b72db03fb", "PC
    v4.5.0.551"), bundles shared across a family ("MOTU Pro Audio Installer" for every
    AVB interface), and at most a "Universal Firmware Updater v2026.2" -- the updater
    tool's version, not the firmware it installs. Tracking any of those as a device's
    firmware would report a driver's number as the device's.

    **The version is the download's own, without its build.** "v11.36+101486" is 11.36.
    Electric Keys' row is named "Electric Keys 1.0.6" and its version field says v1.06;
    the field is read, as it is on every other row.

    **A page can carry an older installer beside the current one.** Performer Lite 11
    DE's page lists its own "Performer Lite 11 DE" 11.23 (October 2023) and the generic
    "Performer Lite 11" 11.36 that now installs it. The newest installer row on a
    product's page is its current version, with that row's date.

    **Only the Installer section counts**; a Soundbank or Driver section beside it is
    not the application. MachFive 3, MOTU Instruments and Symphonic Instrument show no
    installer to anonymous visitors ("Some downloads available only to registered
    users") and are not listed.
    """

    manufacturer_name = "MOTU"
    manufacturer_slug = "motu"
    manufacturer_website = "https://motu.com"

    BASE_URL = "https://motu.com"
    FILTER_URL = BASE_URL + "/en-us/download/filters/?category={category}"
    PRODUCT_URL = BASE_URL + "/en-us/download/product/{id}/"
    SOFTWARE_CATEGORIES = (5, 6)

    VERSION = re.compile(r"\bv(?P<version>\d+(?:\.\d+)*)(?:\+[\w.]+)?")
    DATE = re.compile(r"(?P<month>[A-Za-z]{3,9})\.?\s+(?P<day>\d{1,2}),\s*(?P<year>\d{4})")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._devices: Optional[Dict[str, Tuple[str, ScrapedFirmware]]] = None

    # --- parsing ------------------------------------------------------------

    @staticmethod
    def _parse_products(body: str) -> List[Tuple[int, str]]:
        try:
            products = json.loads(body).get("products") or []
        except (ValueError, AttributeError):
            return []
        return [(int(p["id"]), " ".join(str(p["title"]).split())) for p in products if p.get("id") and p.get("title")]

    @classmethod
    def _date(cls, text: str) -> Optional[datetime]:
        matched = cls.DATE.search(text or "")
        if not matched:
            return None
        month = MONTHS.get(matched.group("month")[:3].lower())
        try:
            return datetime(int(matched.group("year")), month, int(matched.group("day"))) if month else None
        except ValueError:
            return None

    def _parse_page(self, html: str) -> Optional[ScrapedFirmware]:
        """The newest row in the page's Installer section."""
        soup = self.parse_html(html)
        rows: List[Tuple[Tuple[int, ...], ScrapedFirmware]] = []
        for table in soup.find_all("table"):
            section = ""
            for part in table.find_all(["thead", "tbody"], recursive=False):
                if part.name == "thead":
                    section = " ".join(part.get_text(" ").split()).lower()
                    continue
                if not section.startswith("installer"):
                    continue
                for row in part.find_all("tr"):
                    spans = [" ".join(span.get_text(" ").split()) for span in row.select("span.vnum")]
                    version = next((self.VERSION.search(text) for text in spans if self.VERSION.search(text)), None)
                    if not version:
                        continue
                    released = next((self._date(text) for text in spans if self._date(text)), None)
                    name = row.find("b")
                    rows.append((
                        tuple(int(n) for n in version.group("version").split(".")),
                        ScrapedFirmware(version=version.group("version"), release_date=released,
                                        changelog=f"Installer: {' '.join(name.get_text(' ').split())}" if name else None),
                    ))
        if not rows:
            return None
        return max(rows, key=lambda pair: pair[0])[1]

    # --- loading ------------------------------------------------------------

    async def _load(self) -> Optional[Dict[str, Tuple[str, ScrapedFirmware]]]:
        if self._devices is not None:
            return self._devices
        products: List[Tuple[int, str]] = []
        for category in self.SOFTWARE_CATEGORIES:
            body = await self.fetch_page(self.FILTER_URL.format(category=category))
            products.extend(self._parse_products(body) if body else [])
        if not products:
            return None

        devices: Dict[str, Tuple[str, ScrapedFirmware]] = {}
        for product_id, title in products:
            url = self.PRODUCT_URL.format(id=product_id)
            html = await self.fetch_page(url)
            firmware = self._parse_page(html) if html else None
            if firmware is None:
                if not html:
                    logger.warning("MOTU download page %s did not load", url)
                continue
            devices.setdefault(title, (url, firmware))
        self._devices = devices or None
        return self._devices

    async def fetch_device_list(self) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error="No MOTU software installers found in its download centre")
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
            return ScraperResult(success=False, error="No MOTU software installers found in its download centre")
        entry = devices.get(device_name)
        return ScraperResult(success=True, firmware_versions=[entry[1]] if entry else [])
