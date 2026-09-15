import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class MooerScraper(BaseScraper):
    """Mooer -- GE and GS multi-effects firmware, from the release cards on each downloads page.

    mooeraudio.com/Downloads.html lists a downloads page per product, eight to an index
    page (``/Downloads/p-8-8.html`` and on). The current pages carry release notes as
    cards:

        <h1>GE1000</h1> ...
        <div class="version-card"><p class="version-header">GE1000 V3.1.0 Update (2026.7.15)</p>
          <div class="version-body"><div class="note-group"><p class="note-subtitle">Added</p>
            <ul class="bullet-list"><li>...</li></ul></div></div></div>

    **Most cards are not firmware.** A GE1000 page interleaves "APP V3.1.1 Update" and
    "MOOER Cloud Mobile App V1.7.0 Update" with its firmware; GE100 Pro, GE200 Pro, the
    Future, GL and Prime series publish only "MS_For_GE100_Pro_V1.3.3"-style editor cards.
    The editor's version is not the firmware's -- GE1000's editor download is V3.1.1
    while its firmware is V3.1.0 -- so a card counts only when its header opens with the
    page's own model. Products with only editor cards are not listed.

    **One card can cover several models, two ways.** "GE150 Plus/Pro V2.1.2 Update" is
    one release for both; "GE150 Plus/Pro/Max Firmware Update (2026.8)" has no version
    and names one per model in its sub-headings ("GE150 Plus V2.1.3", "GE150 Pro
    V2.1.4"), each dated by the card. A card with no model at all ("V2.1.3 Update
    (2026.1.16)") is skipped: the three models number separately, so it is not clear
    whose it is.

    **Dates are written four ways**: "(2026.7.15)", "(Sept 5, 2025)", "(April, 2024)" and
    "(2025.8)". A month alone is stored as the first of it. The "Creation time" at the top
    of every page is when the page was last edited, not a release.

    Not read, checked 2026-09-15: the older pages -- GE250, GE200, GE150, Preamp Live, the
    X2 pedals, Ocean Machine -- have no cards, only hand-typed paragraphs that have
    fallen behind their own downloads (the GE150 notes end at V1.3.7 beside a V1.3.8
    download). The "Time" beside each file is its upload stamp, shared by every file on
    a page.
    """

    manufacturer_name = "Mooer"
    manufacturer_slug = "mooer"
    manufacturer_website = "https://www.mooeraudio.com"

    BASE_URL = "https://www.mooeraudio.com"
    INDEX_URL = BASE_URL + "/Downloads.html"
    MAX_INDEX_PAGES = 10
    PRODUCT_PAGE = re.compile(r"/(?:Downloads_xq/\d+|companyfile/[^/]+-\d+)\.html$")
    DATE_PART = r"(?:\s*[(（](?P<date>[^)）]*)[)）])?"
    VERSIONED = re.compile(
        r"^(?P<models>\S+?(?:\s+\S+?)*?)\s+(?:Firmware\s+(?:Update\s+)?)?[Vv](?P<version>\d+(?:\.\d+)+)"
        r"(?:\s+Update(?:\s+Log)?)?" + DATE_PART + "$"
    )
    UNVERSIONED = re.compile(r"^(?P<models>.+?)\s+Firmware\s+Update" + DATE_PART + "$")
    NUMERIC_DATE = re.compile(r"^(\d{4})\.(\d{1,2})(?:\.(\d{1,2}))?$")
    WORDS_DATE = re.compile(r"^([A-Za-z]{3})[a-z]*\.?,?\s+(?:(\d{1,2})(?:st|nd|rd|th)?,?\s+)?(\d{4})$")
    NOTES_LIMIT = 4000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._devices: Optional[Dict[str, Tuple[str, List[ScrapedFirmware]]]] = None

    # --- parsing ------------------------------------------------------------

    @staticmethod
    def _text(element) -> str:
        return " ".join(element.get_text(" ").split())

    @staticmethod
    def _expand(models: str) -> List[str]:
        """"GE150 Plus/Pro/Max" -> GE150 Plus, GE150 Pro, GE150 Max."""
        parts = [part.strip() for part in models.split("/")]
        base = parts[0].rsplit(" ", 1)[0] if len(parts) > 1 and " " in parts[0] else ""
        return [parts[0]] + [f"{base} {part}".strip() for part in parts[1:]]

    def _parse_date(self, text: Optional[str]) -> Optional[datetime]:
        text = " ".join((text or "").split())
        try:
            numeric = self.NUMERIC_DATE.match(text)
            if numeric:
                year, month, day = numeric.groups()
                return datetime(int(year), int(month), int(day or 1))
            words = self.WORDS_DATE.match(text)
            if words:
                month, day, year = words.groups()
                return datetime.strptime(f"{month.title()} {day or 1} {year}", "%b %d %Y")
        except ValueError:
            return None
        return None

    def _parse_index(self, html: str) -> Tuple[List[str], List[str]]:
        """(product page URLs, further index page URLs)."""
        soup = self.parse_html(html)
        products: List[str] = []
        for link in soup.find_all("a", href=True):
            if self.PRODUCT_PAGE.search(link["href"]):
                url = urljoin(self.BASE_URL, link["href"])
                if url not in products:
                    products.append(url)
        pages = [urljoin(self.BASE_URL, link["href"]) for link in soup.select("a.page_num[href]")
                 if link["href"].startswith("/")]
        return products, pages

    def _card_notes(self, container) -> Optional[str]:
        lines = [self._text(element) for element in container.find_all(["p", "li"])]
        notes = "\n".join(line for line in lines if line)
        return notes[: self.NOTES_LIMIT] or None

    def _parse_page(self, html: str) -> Dict[str, List[ScrapedFirmware]]:
        soup = self.parse_html(html)
        heading = soup.find("h1")
        title = self._text(heading) if heading else ""
        models = set(self._expand(title)) if title else set()
        releases: Dict[str, List[ScrapedFirmware]] = {}

        def add(model: str, version: str, date: Optional[datetime], notes: Optional[str]) -> None:
            existing = releases.setdefault(model, [])
            if version not in {release.version for release in existing}:
                existing.append(ScrapedFirmware(version=version, release_date=date, changelog=notes))

        for card in soup.select("div.version-card"):
            header = card.find("p", class_="version-header")
            body = card.find(class_="version-body") or card
            text = self._text(header) if header else ""
            versioned = self.VERSIONED.match(text)
            if versioned:
                named = [model for model in self._expand(versioned.group("models")) if model in models]
                for model in named:
                    add(model, versioned.group("version"), self._parse_date(versioned.group("date")),
                        self._card_notes(body))
                continue
            unversioned = self.UNVERSIONED.match(text)
            if not unversioned:
                continue
            date = self._parse_date(unversioned.group("date"))
            for group in body.select("div.note-group"):
                subtitle = group.find("p", class_="note-subtitle")
                sub = self.VERSIONED.match(self._text(subtitle)) if subtitle else None
                if not sub:
                    continue
                items = "\n".join(self._text(item) for item in group.find_all("li"))
                for model in self._expand(sub.group("models")):
                    if model in models:
                        add(model, sub.group("version"), date, items[: self.NOTES_LIMIT] or None)
        return releases

    # --- loading ------------------------------------------------------------

    async def _load(self) -> Optional[Dict[str, Tuple[str, List[ScrapedFirmware]]]]:
        if self._devices is not None:
            return self._devices
        first = await self.fetch_page(self.INDEX_URL)
        if not first:
            return None
        products, pages = self._parse_index(first)
        for page in pages[: self.MAX_INDEX_PAGES]:
            html = await self.fetch_page(page)
            for url in (self._parse_index(html)[0] if html else []):
                if url not in products:
                    products.append(url)
        devices: Dict[str, Tuple[str, List[ScrapedFirmware]]] = {}
        for url in products:
            html = await self.fetch_page(url)
            if not html:
                logger.warning("Mooer downloads page %s did not load", url)
                continue
            for model, releases in self._parse_page(html).items():
                devices.setdefault(model, (url, releases))
        self._devices = devices or None
        return self._devices

    async def fetch_device_list(self) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error="No Mooer downloads page published a firmware release")
        return ScraperResult(
            success=True,
            devices=[ScrapedDevice(name=name, category="guitar_pedal", firmware_page_url=url, product_url=url)
                     for name, (url, _releases) in devices.items()],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error="No Mooer downloads page published a firmware release")
        entry = devices.get(device_name)
        return ScraperResult(success=True, firmware_versions=entry[1] if entry else [])
