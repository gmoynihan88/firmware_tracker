import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class ConductiveLabsScraper(BaseScraper):
    """Conductive Labs -- The NDLR (Rev1 and Rev2) and MRCC firmware, from the firmware download pages.

    conductivelabs.com/download/ links a firmware page per product family. Each links its
    firmware as a zip under a bold paragraph saying which hardware it is for:

        <p><strong>Only for the original version of The NDLR (rev1) with a blue/grey base ...</strong></p>
        <p><a href=".../2023/10/NDLRv1.1.086.zip">NDLRv1.1.086</a>.zip (Oct 27, 2023)</p>
        <p><strong>Firmware update for The NDLR rev2 with the powder coated RED base ...</strong></p>
        <p><a href=".../2025/08/NDLR_Rev2_firmware_v3_3_6.zip">NDLR_Rev2_firmware_v3_3_6</a> (August 6, 2025)</p>

    **The NDLR is two products.** Rev1 and Rev2 take different firmware and loading the
    wrong one blanks the screen, so each file goes to the revision the bold paragraph
    before it names -- including "the previous version release 2 firmware for The NDLR
    Rev2" (``NDLRv2.0.014.zip``), whose file name says neither.

    **Versions come from the file name**, written with dots ("1.1.086") or underscores
    ("v3_3_6"); both are stored dotted, the leading zeros kept. A version uses one
    separator throughout: ``MRCC_1.1.095_09-10-2025`` is 1.1.095, and a pattern that
    accepted either separator read it as 1.1.095.09.

    **Dates are the ones printed beside the link.** MRCC's only date is in its file name,
    ``MRCC_1.1.095_09-10-2025.zip``, which reads as either 9 October or 10 September; it
    is stored undated rather than guessed. The ``uploads/2025/10/`` folder is the upload
    month, not a release date. MRCC's page lists that release's changes, which become its
    notes; The NDLR's point to Discord and have none.
    """

    manufacturer_name = "Conductive Labs"
    manufacturer_slug = "conductivelabs"
    manufacturer_website = "https://conductivelabs.com"

    INDEX_URL = "https://conductivelabs.com/download/"
    FIRMWARE_PAGE = re.compile(r"/download/[a-z0-9-]*firmware[a-z0-9-]*/?$")
    FILE = re.compile(r"/(?P<stem>[A-Za-z0-9_.-]+)\.zip$")
    FILE_VERSION = re.compile(r"v?(?P<version>\d+(?:\.\d+)+|\d+(?:_\d+)+)")
    REVISION = re.compile(r"\brev\s?(?P<rev>\d)\b", re.I)
    DATE = re.compile(r"\((?P<month>[A-Za-z]{3})[a-z]*\.?\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})\)")
    NOTES_LIMIT = 4000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._devices: Optional[Dict[str, Tuple[str, List[ScrapedFirmware]]]] = None

    # --- parsing ------------------------------------------------------------

    @staticmethod
    def _text(element) -> str:
        return " ".join(element.get_text(" ").split())

    def _parse_index(self, html: str) -> List[str]:
        urls: List[str] = []
        for link in self.parse_html(html).find_all("a", href=True):
            if self.FIRMWARE_PAGE.search(link["href"].split("#")[0]):
                url = urljoin(self.INDEX_URL, link["href"].split("#")[0])
                if url not in urls:
                    urls.append(url)
        return urls

    def _parse_date(self, text: str) -> Optional[datetime]:
        matched = self.DATE.search(text)
        if not matched:
            return None
        try:
            return datetime.strptime(f"{matched.group('month')} {matched.group('day')} {matched.group('year')}", "%b %d %Y")
        except ValueError:
            return None

    def _product(self, stem: str, context: str) -> Optional[str]:
        if stem.upper().startswith("NDLR"):
            revision = self.REVISION.search(stem) or self.REVISION.search(context)
            return f"The NDLR Rev{revision.group('rev')}" if revision else None
        if stem.upper().startswith("MRCC"):
            return "MRCC"
        return None

    def _notes(self, anchor_paragraph) -> Optional[str]:
        lines: List[str] = []
        for element in anchor_paragraph.find_next_siblings():
            next_download = element.name == "p" and element.find("a", href=self.FILE)
            if element.name in ("h2", "h3", "h4", "h5") or next_download:
                break
            if element.name in ("ul", "ol"):
                lines.extend(self._text(item) for item in element.find_all("li"))
            elif element.name == "p" and element.find("strong") and self._text(element) == self._text(element.find("strong")):
                lines.append(self._text(element))
        notes = "\n".join(line for line in lines if line)
        return notes[: self.NOTES_LIMIT] or None

    def _parse_page(self, html: str) -> Dict[str, List[ScrapedFirmware]]:
        firmware: Dict[str, List[ScrapedFirmware]] = {}
        context = ""
        for paragraph in self.parse_html(html).find_all("p"):
            link = paragraph.find("a", href=self.FILE)
            if not link:
                context = self._text(paragraph)
                continue
            stem = self.FILE.search(link["href"]).group("stem")
            version = self.FILE_VERSION.search(stem)
            product = self._product(stem, context)
            if not version or not product:
                continue
            notes = self._notes(paragraph) if product == "MRCC" else None
            releases = firmware.setdefault(product, [])
            releases.append(ScrapedFirmware(version=version.group("version").replace("_", "."),
                                            release_date=self._parse_date(self._text(paragraph)), changelog=notes))
        return firmware

    # --- loading ------------------------------------------------------------

    async def _load(self) -> Optional[Dict[str, Tuple[str, List[ScrapedFirmware]]]]:
        if self._devices is not None:
            return self._devices
        index = await self.fetch_page(self.INDEX_URL)
        devices: Dict[str, Tuple[str, List[ScrapedFirmware]]] = {}
        for url in self._parse_index(index) if index else []:
            html = await self.fetch_page(url)
            parsed = self._parse_page(html) if html else {}
            if not parsed:
                logger.warning("Conductive Labs firmware page %s did not load or linked no firmware", url)
            for product, releases in parsed.items():
                devices.setdefault(product, (url, releases))
        self._devices = devices or None
        return self._devices

    async def fetch_device_list(self) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error="No Conductive Labs firmware page could be read")
        return ScraperResult(
            success=True,
            devices=[ScrapedDevice(name=name, category="midi_controller", firmware_page_url=url, product_url=url)
                     for name, (url, _releases) in devices.items()],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error="No Conductive Labs firmware page could be read")
        entry = devices.get(device_name)
        return ScraperResult(success=True, firmware_versions=entry[1] if entry else [])
