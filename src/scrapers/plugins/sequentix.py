import logging
import re
from datetime import datetime
from typing import Dict, List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class SequentixScraper(BaseScraper):
    """Sequentix -- Cirklon, Cirklon 2 and P3 sequencer firmware, from the downloads page.

    sequentix.com/pages/cirklon-p3-downloads (a Shopify page of rich-text blocks) states
    each Cirklon's current OS in one paragraph, with its date after a line break:

        <p>Current <strong>Cirklon 2</strong> Release OS v1.22d<br/>11/12/2024</p>

    **Cirklon and Cirklon 2 are separate products**, with separate firmware images the
    page warns not to swap, so each is its own device. Versions keep their letter
    ("1.22d", "1.22e"): the two units are on different builds of 1.22.

    **Dates are day-first.** "11/12/2024" alone could be either, but the same page writes
    "24/2/2025" and "30/03/2011", which can only be day-first.

    **The P3 page is mostly betas.** Its downloads are listed as "P3 OS v4.5 beta 3 SYX
    format", "P3 OS v3.1.007 beta 13 MID format" and one release, "P3 OS v3.1.006 rev C",
    each file with its date in the caption below it. Only lines naming a SYX or MID file
    count -- "P3 OS v3.1.006 rev B Release Notes" is a text file, not a release -- and a
    version followed by "beta 3" is not a version followed by its file format, so betas do
    not match. A revision letter joins the version: 3.1.006C.

    Notes are not read: each release's notes are linked as a .txt file.
    """

    manufacturer_name = "Sequentix"
    manufacturer_slug = "sequentix"
    manufacturer_website = "https://www.sequentix.com"

    DOWNLOADS_URL = "https://www.sequentix.com/pages/cirklon-p3-downloads"
    CIRKLON = re.compile(
        r"^Current\s+(?P<product>Cirklon(?:\s*2)?)\s+Release\s+OS\s+v(?P<version>\d+(?:\.\d+)+[a-z]?)"
        r"\s+(?P<date>\d{1,2}/\d{1,2}/\d{4})$", re.I
    )
    P3 = re.compile(r"^P3\s+OS\s+v(?P<version>\d+(?:\.\d+)+)(?:\s+rev\s+(?P<rev>[A-Z]))?\s+(?:SYX|MID)\s+format$", re.I)
    DATE = re.compile(r"^(?P<day>\d{1,2})/(?P<month>\d{1,2})/(?P<year>\d{4})$")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._devices: Optional[Dict[str, List[ScrapedFirmware]]] = None

    # --- parsing ------------------------------------------------------------

    @staticmethod
    def _text(element) -> str:
        return " ".join(element.get_text(" ").split())

    def _parse_date(self, text: str) -> Optional[datetime]:
        matched = self.DATE.match(text.strip())
        if not matched:
            return None
        try:
            return datetime(int(matched.group("year")), int(matched.group("month")), int(matched.group("day")))
        except ValueError:
            return None

    def _add(self, devices: Dict[str, List[ScrapedFirmware]], name: str, version: str, date: Optional[datetime]) -> None:
        releases = devices.setdefault(name, [])
        if version not in {release.version for release in releases}:
            releases.append(ScrapedFirmware(version=version, release_date=date))

    def _parse(self, html: str) -> Dict[str, List[ScrapedFirmware]]:
        devices: Dict[str, List[ScrapedFirmware]] = {}
        for paragraph in self.parse_html(html).find_all("p"):
            text = self._text(paragraph)
            cirklon = self.CIRKLON.match(text)
            if cirklon:
                self._add(devices, cirklon.group("product"), cirklon.group("version"),
                          self._parse_date(cirklon.group("date")))
                continue
            p3 = self.P3.match(text)
            if not p3:
                continue
            caption = paragraph.find_next("p")
            date = self._parse_date(self._text(caption)) if caption else None
            self._add(devices, "P3", p3.group("version") + (p3.group("rev") or ""), date)
        return devices

    # --- loading ------------------------------------------------------------

    async def _load(self) -> Optional[Dict[str, List[ScrapedFirmware]]]:
        if self._devices is not None:
            return self._devices
        html = await self.fetch_page(self.DOWNLOADS_URL)
        self._devices = (self._parse(html) if html else {}) or None
        return self._devices

    async def fetch_device_list(self) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error="Sequentix downloads page named no firmware")
        return ScraperResult(
            success=True,
            devices=[ScrapedDevice(name=name, category="midi_controller", firmware_page_url=self.DOWNLOADS_URL,
                                   product_url=self.DOWNLOADS_URL) for name in devices],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error="Sequentix downloads page named no firmware")
        return ScraperResult(success=True, firmware_versions=devices.get(device_name, []))
