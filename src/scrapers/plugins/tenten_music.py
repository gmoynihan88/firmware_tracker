import logging
import re
from datetime import datetime
from typing import Dict, Optional, Tuple

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class TenTenMusicScraper(BaseScraper):
    """1010music -- the current firmware of every sampler and module, from the downloads page.

    1010music.com/downloads gives each product one block: its name, the month of its
    current firmware, the version, the download, and a "Release Notes" accordion.

        <h2 style="text-align: center;">blackbox</h2><p style="text-align: center;">July 2026</p>
        ... <p><strong>Firmware version 3.1.9</strong></p>
        <a href=".../2026/07/blackbox-3.1.9.zip" class="button primary"><span>Download</span></a>

    **The month is the release's.** Checked against the release-notes PDFs the blocks
    link: bento 1.5.32 under "July 2026" has notes dated 2026-07-31, bluebox 1.5.2 under
    "August 2026" has notes from that month. It is stored as the first of the month.

    **The label can lag the file.** nanobox | tangerine says "Firmware version 1.2.8"
    beside NANOTANG1228.zip, under release notes headed "Tangerine 1.2.28". Files are
    named two ways: "blackbox-3.1.9.zip" carries its version whole and is taken over the
    label; "NANOTANG1228.zip" drops the dots, so it cannot be read alone -- but when its
    digits run on from the label's all-but-last part ("12" + "28"), the rest is the real
    last part.

    **Current version only.** Older and beta firmware lives on 1010music's Discord
    server; the forum's firmware board, which held it, was retired in August 2026. Links
    to earlier release-notes PDFs ("v 1.4 Release Notes") describe versions without
    downloads or a structured date and are not read.

    Headings inside the release notes ("Tangerine 1.2.28", "Version 1.2.2") and the
    newsletter form's heading are not product blocks: the next "Firmware version" after
    them is outside their block, or there is none. A block with no month is kept, undated.
    """

    manufacturer_name = "1010music"
    manufacturer_slug = "1010music"
    manufacturer_website = "https://1010music.com"

    DOWNLOADS_URL = "https://1010music.com/downloads"
    MONTH = re.compile(r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})$")
    LABEL = re.compile(r"Firmware\s+version\s+v?(\d+(?:\.\d+)+)", re.I)
    DOTTED_FILE = re.compile(r"[-_]v?(\d+(?:\.\d+)+)\.zip$", re.I)
    DOTLESS_FILE = re.compile(r"(\d{3,})\.zip$", re.I)
    NOTES_LIMIT = 4000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._devices: Optional[Dict[str, ScrapedFirmware]] = None

    # --- parsing ------------------------------------------------------------

    @staticmethod
    def _text(element) -> str:
        return " ".join(element.get_text(" ").split())

    def _version(self, label: str, href: str) -> str:
        filename = href.split("?")[0].rsplit("/", 1)[-1]
        dotted = self.DOTTED_FILE.search(filename)
        if dotted:
            return dotted.group(1)
        dotless = self.DOTLESS_FILE.search(filename)
        parts = label.split(".")
        if dotless and len(parts) > 1:
            prefix = "".join(parts[:-1])
            digits = dotless.group(1)
            if digits.startswith(prefix) and len(digits) > len(prefix):
                return ".".join(parts[:-1] + [str(int(digits[len(prefix):]))])
        return label

    def _parse(self, html: str) -> Dict[str, ScrapedFirmware]:
        devices: Dict[str, ScrapedFirmware] = {}
        for heading in self.parse_html(html).find_all("h2"):
            month_line = heading.find_next_sibling("p")
            month = self.MONTH.match(self._text(month_line)) if month_line else None
            row = heading.find_parent(class_="row")
            if not row:
                continue
            label_text = heading.find_next(string=self.LABEL)
            if label_text is None or row not in label_text.parents:
                logger.warning("1010music block %r names no firmware version", self._text(heading))
                continue
            label = self.LABEL.search(label_text).group(1)
            download = label_text.find_next("a", href=re.compile(r"\.zip(?:\?|$)", re.I))
            version = self._version(label, download["href"]) if download and row in download.parents else label
            notes_item = next((item for item in row.select(".accordion-item")
                               if "Release Notes" in self._text(item.select_one(".accordion-title") or item)), None)
            inner = notes_item.select_one(".accordion-inner") if notes_item else None
            lines = [self._text(el) for el in inner.find_all(["h2", "h3", "p", "li"])] if inner else []
            notes = "\n".join(line for line in lines if line)[: self.NOTES_LIMIT] or None
            devices.setdefault(self._text(heading), ScrapedFirmware(
                version=version,
                release_date=datetime.strptime(f"{month.group(1)} 1 {month.group(2)}", "%B %d %Y") if month else None,
                changelog=notes,
            ))
        return devices

    # --- loading ------------------------------------------------------------

    async def _load(self) -> Optional[Dict[str, ScrapedFirmware]]:
        if self._devices is not None:
            return self._devices
        html = await self.fetch_page(self.DOWNLOADS_URL)
        self._devices = (self._parse(html) if html else {}) or None
        return self._devices

    async def fetch_device_list(self) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error="1010music downloads page named no firmware")
        return ScraperResult(
            success=True,
            devices=[ScrapedDevice(name=name, category="synthesizer", firmware_page_url=self.DOWNLOADS_URL,
                                   product_url=self.DOWNLOADS_URL) for name in devices],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error="1010music downloads page named no firmware")
        firmware = devices.get(device_name)
        return ScraperResult(success=True, firmware_versions=[firmware] if firmware else [])
