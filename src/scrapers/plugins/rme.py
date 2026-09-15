import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class RMEScraper(BaseScraper):
    """RME -- the converters, preamps and cards whose firmware RME states as one version.

    Every RME download is an item on `/downloads.html`, and the firmware ones carry
    `data-driver="flash"` -- the other 70 are drivers, TotalMix and DigiCheck, which
    are not firmware and are never read:

        <li data-driver="flash" data-product="104">
          <div class="sub-row-title"><div>M-1620 Pro D Firmware Update</div>
            <div>2026-09-07</div><div><a href=".../M-1620_Pro_D_1_3_3.zip">...</a></div></div>
          <div class="sub-row-description"><p><strong>Firmware 1.3.3</strong>. Main update...</p></div>
          <div class="supported-products"><b>Supported products</b> M-1620 Pro D</div>

    **What is catalogued.** A firmware item counts when its title names one product and
    its description states one firmware version: "Firmware 1.3.3", "includes firmware
    version 3.0.8", "Firmware version 1.5.0-67", "update to firmware revision 1.71",
    "v 272", "version 7". The product is taken from the title, not the supported-
    products list: "Firmware update for M-32 AD Pro II" (3.0.7) and "... M-32 DA Pro II"
    (3.0.8) both list "M-32 AD / M-32 DA Pro II", and would collide.

    **Descriptions name other versions too.** The HDSPe AoX package states "Driver
    1.01 with Settings 1.30 and Firmware version 1.5.0-67"; the M-Series tool adds
    "MIDI Remote ... version 1.6 and higher". The statements are tried in order --
    "firmware ..." first, a bare "version N" or "v N" only when there is none -- and a
    version cannot end just before a dot and another digit, which is how "1.5.0-67"
    also yielded "1" and made the description look ambiguous.

    **The page contains the literal text "[nbsp]"**, a leftover of its editor:
    "Update to firmware revision[nbsp] 1.71". It is read as a space; otherwise the
    Fireface 400 and 800 archive items state no version.

    The same version offered for Mac and Windows is one release, dated by the earlier
    item.

    **What is not, yet.** RME's current interfaces -- Babyface Pro FS, Fireface UCX II,
    UFX III, UFX+, 802 FS, ADI-2, MADIface, Digiface USB/Dante/Ravenna, the HDSPe series
    -- are flashed by multi-product tools whose descriptions give per-component
    revision lists rather than a version:

        Update to version UFX: 361/163/344/29, ..., Babyface Pro & FS: 211/322.
        Update to firmware version USB 55, TB 112, DSP 62 (AKM) and USB 72, ... (ESS).

    The Mac and Windows descriptions even order the components differently ("802 FS:
    227/ 215/ 31" against "227/31/215"). Those are published, but not as one comparable
    version, so they are left out rather than stored in a form that cannot say which is
    newer.
    """

    manufacturer_name = "RME"
    manufacturer_slug = "rme"
    manufacturer_website = "https://rme-audio.de"

    DOWNLOADS_URL = "https://rme-audio.de/downloads.html"

    PLATFORM = re.compile(r"^(?:macOS|Mac\s+OS\s+X\s+Intel|Mac\s+OS\s+X|Mac\s+OS|Mac|Windows)\s+", re.I)
    TITLE_PATTERNS = (
        re.compile(r"^Firmware\s+update\s+(?:for\s+)?(?P<name>.+)$", re.I),
        re.compile(r"^(?P<name>.+?)\s+Firmware\s+Update(?:\s+\d+\.x)?$", re.I),
        re.compile(r"^(?P<name>.+?)\s+Driver\s+&\s+Firmware\s+Package$", re.I),
        re.compile(r"^(?:Flash|Firmware)\s+Update(?:\s+Tool)?\s+(?:for\s+)?(?P<name>.+?)(?:\s*\([^)]*\))?$", re.I),
        re.compile(r"^(?P<name>.+?)\s+(?:Thunderbolt\s+)?Flash\s+Update\s+Tool(?:\s*\([^)]*\))?$", re.I),
    )
    # A title naming several products ("Fireface UFX/UCX/802", "HDSPe MADI FX & MADIface XT").
    SEVERAL = re.compile(r"[/,&]|\sand\s")
    # Where a version may end: not in the middle of "1.5.0-67" or "3.0.8".
    _END = r"(?=[\s,;)]|\.(?!\d)|$)"
    # In priority order: the first that finds anything decides.
    VERSION_STATEMENTS = (
        re.compile(rf"\bfirmware(?:\s+(?:version|revision))?\s+(?P<v>\d+(?:\.\d+)*[a-z]?(?:-\d+)?){_END}", re.I),
        re.compile(rf"\b(?:update\s+to\s+)?version\s+(?P<v>\d+(?:\.\d+)*[a-z]?){_END}", re.I),
        re.compile(rf"(?:^|[\s,])v\s+(?P<v>\d+(?:\.\d+)*){_END}", re.I),
    )
    CATEGORIES = {"ARC USB": "midi_controller"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._products: Optional[Dict[str, List[ScrapedFirmware]]] = None

    @staticmethod
    def _text(element) -> str:
        if element is None:
            return ""
        return " ".join(element.get_text(" ").replace("[nbsp]", " ").split())

    def _product_name(self, title: str) -> Optional[str]:
        title = self.PLATFORM.sub("", " ".join(title.split()))
        for pattern in self.TITLE_PATTERNS:
            matched = pattern.match(title)
            if matched:
                name = matched.group("name").strip(" -")
                if not name or self.SEVERAL.search(name):
                    return None
                return name
        return None

    def _firmware_version(self, description: str) -> Optional[str]:
        """The one version the description states, by the first statement form present."""
        for pattern in self.VERSION_STATEMENTS:
            found = {matched.group("v") for matched in pattern.finditer(description)}
            if found:
                return found.pop() if len(found) == 1 else None
        return None

    def _parse_downloads(self, html: str) -> Dict[str, List[ScrapedFirmware]]:
        soup = self.parse_html(html)
        releases: Dict[Tuple[str, str], ScrapedFirmware] = {}
        order: List[str] = []
        for item in soup.select("ul.dl-v2-downloads > li"):
            if item.get("data-driver") != "flash":
                continue
            title_row = item.select_one("div.sub-row-title")
            cells = title_row.find_all("div", recursive=False) if title_row else []
            if len(cells) < 2:
                continue
            name = self._product_name(self._text(cells[0]))
            description = self._text(item.select_one("div.sub-row-description"))
            version = self._firmware_version(description) if name else None
            if not name or not version:
                continue
            try:
                released = datetime.strptime(self._text(cells[1]), "%Y-%m-%d")
            except ValueError:
                released = None
            link = item.select_one("div.sub-row-title a[href]")
            key = (name, version)
            existing = releases.get(key)
            if existing is None:
                releases[key] = ScrapedFirmware(
                    version=version, release_date=released,
                    download_url=link["href"] if link else None, changelog=description or None,
                )
                if name not in order:
                    order.append(name)
            elif released and (existing.release_date is None or released < existing.release_date):
                existing.release_date = released  # the same version for the other platform

        products: Dict[str, List[ScrapedFirmware]] = {name: [] for name in order}
        for (name, _version), firmware in releases.items():
            products[name].append(firmware)
        for versions in products.values():
            versions.sort(key=lambda fw: fw.release_date or datetime.min, reverse=True)
        return products

    async def _load(self) -> Optional[Dict[str, List[ScrapedFirmware]]]:
        if self._products is None:
            html = await self.fetch_page(self.DOWNLOADS_URL)
            products = self._parse_downloads(html) if html else {}
            self._products = products or None
        return self._products

    async def fetch_device_list(self) -> ScraperResult:
        products = await self._load()
        if not products:
            return ScraperResult(success=False, error=f"No RME firmware items found at {self.DOWNLOADS_URL}")
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category=self.CATEGORIES.get(name, "audio_interface"),
                    firmware_page_url=self.DOWNLOADS_URL,
                    product_url=self.DOWNLOADS_URL,
                )
                for name in products
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        products = await self._load()
        if not products:
            return ScraperResult(success=False, error=f"No RME firmware items found at {self.DOWNLOADS_URL}")
        return ScraperResult(success=True, firmware_versions=list(products.get(device_name, [])))
