import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class XLNAudioScraper(BaseScraper):
    """XLN Audio -- every plug-in and its installer, dated, from the release notes table.

    xlnaudio.com/release_notes is one paged table, fifteen rows a page, newest first:

        <tr><td>XO</td><td>1.8.10</td><td><ul><li>Fixed a bug ...</li></ul></td>
            <td>Aug 7, 2026</td></tr>

    Pages are read until one comes back with no rows (``?page=4`` does, today).

    **Only products named in the page's own filter are kept.** The table's default view
    is that filter's "All Products". An unrecognised ``?filter=`` value shows everything
    instead, and that adds some thirty rows for XO expansions and ADpaks ("Phonk 1.0.1",
    "Memory Card 1.0.0 -- Final build of Memory Card xopak") and for "Life DAW Recorder",
    a component. Those are content, not software, so a row counts only when its name is
    a filter option -- or the option plus a generation number, since the option reads
    "Addictive Drums" and the rows "Addictive Drums 2".

    **The history is short.** The oldest row is Life 1.2.0 from March 2025; filtering to
    one product reaches no further back. Earlier releases are not published.

    "XLN Online Installer", which installs and updates the rest, is kept as a product,
    as Waves Central is in ``waves.py``.
    """

    manufacturer_name = "XLN Audio"
    manufacturer_slug = "xlnaudio"
    manufacturer_website = "https://www.xlnaudio.com"

    BASE_URL = "https://www.xlnaudio.com"
    RELEASE_NOTES_URL = BASE_URL + "/release_notes"
    MAX_PAGES = 20
    VERSION = re.compile(r"^v?(\d+(?:\.\d+)+)$")
    DATE = re.compile(r"^([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),\s+(\d{4})$")
    NOTES_LIMIT = 4000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._devices: Optional[Dict[str, Tuple[str, List[ScrapedFirmware]]]] = None

    # --- parsing ------------------------------------------------------------

    @staticmethod
    def _text(element) -> str:
        return " ".join(element.get_text(" ").split())

    def _parse_date(self, text: str) -> Optional[datetime]:
        matched = self.DATE.match(text)
        if not matched:
            return None
        try:
            return datetime.strptime(" ".join(matched.groups()), "%b %d %Y")
        except ValueError:
            return None

    def _parse_filters(self, html: str) -> Dict[str, str]:
        """Filter label -> its value, from the table's product select."""
        select = self.parse_html(html).find("select", attrs={"name": "filter"})
        options = select.find_all("option") if select else []
        return {self._text(option): option.get("value", "") for option in options
                if option.get("value") and option.get("value") != "all"}

    def _parse_rows(self, html: str) -> List[Tuple[str, ScrapedFirmware]]:
        rows: List[Tuple[str, ScrapedFirmware]] = []
        for row in self.parse_html(html).select("table tbody tr"):
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            version = self.VERSION.match(self._text(cells[1]))
            if not version:
                continue
            items = [self._text(item) for item in cells[2].find_all("li")]
            notes = "\n".join(item for item in items if item) or self._text(cells[2])
            rows.append((self._text(cells[0]), ScrapedFirmware(
                version=version.group(1), release_date=self._parse_date(self._text(cells[3])),
                changelog=notes[: self.NOTES_LIMIT] or None,
            )))
        return rows

    @staticmethod
    def _filter_for(name: str, filters: Dict[str, str]) -> Optional[str]:
        for label, value in filters.items():
            if name == label or re.fullmatch(re.escape(label) + r"\s+\d+", name):
                return value
        return None

    # --- loading ------------------------------------------------------------

    async def _load(self) -> Optional[Dict[str, Tuple[str, List[ScrapedFirmware]]]]:
        if self._devices is not None:
            return self._devices
        first = await self.fetch_page(self.RELEASE_NOTES_URL)
        if not first:
            return None
        filters = self._parse_filters(first)
        rows = self._parse_rows(first)
        seen = {(name, firmware.version) for name, firmware in rows}
        for page in range(2, self.MAX_PAGES + 1):
            html = await self.fetch_page(f"{self.RELEASE_NOTES_URL}?page={page}")
            fresh = [(name, fw) for name, fw in (self._parse_rows(html) if html else [])
                     if (name, fw.version) not in seen]
            if not fresh:
                break
            rows.extend(fresh)
            seen.update((name, fw.version) for name, fw in fresh)
        devices: Dict[str, Tuple[str, List[ScrapedFirmware]]] = {}
        for name, firmware in rows:
            value = self._filter_for(name, filters)
            if value is None:
                logger.debug("XLN Audio row %s %s is not a filter product; skipped", name, firmware.version)
                continue
            url = f"{self.RELEASE_NOTES_URL}?filter={quote(value)}"
            devices.setdefault(name, (url, []))[1].append(firmware)
        self._devices = devices or None
        return self._devices

    async def fetch_device_list(self) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error="XLN Audio release notes listed no products")
        return ScraperResult(
            success=True,
            devices=[ScrapedDevice(name=name, category="vst_plugin", firmware_page_url=url, product_url=url)
                     for name, (url, _releases) in devices.items()],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error="XLN Audio release notes listed no products")
        entry = devices.get(device_name)
        return ScraperResult(success=True, firmware_versions=entry[1] if entry else [])
