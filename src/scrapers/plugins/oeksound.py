import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class OeksoundScraper(BaseScraper):
    """oeksound -- soothe3, soothe2, spiff, bloom, soothe live and the original soothe, from their change logs.

    oeksound.com/downloads links a change log per plug-in (``/changelog/soothe3``,
    ``/changelog/legacy-soothe``), and each lists every release:

        <h2 class="mb-4">soothe3 change log</h2>
        <div class="mb-5"><h3>1.0.5</h3>
          <small class="text-muted mb-2 d-block">Released on June 29, 2026</small><ul><li>...</li></ul></div>

    **Older entries have no date line.** spiff's releases before 1.2.0 and the original
    soothe's before 1.4.0 go straight from the version to the notes; they are stored
    undated rather than borrowing a neighbour's date.

    **Versions are hand-typed.** spiff has "1.0.1a" and "1.0.1b" -- real re-releases,
    kept as written -- and the original soothe has "1.1.3'" with a stray apostrophe,
    which is dropped.

    **Notes nest.** "Bug fixes" is a list item holding its own list; each item's own text
    is one line, so the heading is not repeated with its children run into it. A first
    release's note is a paragraph instead ("<p>Initial release.</p>").

    Products are discovered from the downloads page's change-log links and named by each
    change log's heading, less " change log".
    """

    manufacturer_name = "oeksound"
    manufacturer_slug = "oeksound"
    manufacturer_website = "https://oeksound.com"

    BASE_URL = "https://oeksound.com"
    DOWNLOADS_URL = BASE_URL + "/downloads"
    CHANGELOG_LINK = re.compile(r"^(?:https?://(?:www\.)?oeksound\.com)?(/changelog/[a-z0-9-]+)/?$")
    TITLE = re.compile(r"^(?P<name>.+?)\s+change\s+log$", re.I)
    VERSION = re.compile(r"^v?(?P<version>\d+(?:\.\d+)+[a-z]?)'?$")
    RELEASED = re.compile(r"^Released\s+on\s+(?P<date>[A-Za-z]+\s+\d{1,2},\s+\d{4})$", re.I)
    NOTES_LIMIT = 4000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._devices: Optional[Dict[str, Tuple[str, List[ScrapedFirmware]]]] = None

    # --- parsing ------------------------------------------------------------

    @staticmethod
    def _text(element) -> str:
        return " ".join(element.get_text(" ").split())

    def _parse_downloads(self, html: str) -> List[str]:
        urls: List[str] = []
        for link in self.parse_html(html).find_all("a", href=True):
            matched = self.CHANGELOG_LINK.match(link["href"])
            if matched:
                url = urljoin(self.BASE_URL, matched.group(1))
                if url not in urls:
                    urls.append(url)
        return urls

    @staticmethod
    def _own_text(item) -> str:
        """An <li>'s text without the text of any list nested inside it."""
        parts = [string for string in item.find_all(string=True)
                 if not any(parent.name in ("ul", "ol") for parent in string.parents
                            if parent is not item and item in parent.parents)]
        return " ".join(" ".join(parts).split())

    def _parse_date(self, text: str) -> Optional[datetime]:
        matched = self.RELEASED.match(" ".join(text.split()))
        if not matched:
            return None
        try:
            return datetime.strptime(matched.group("date"), "%B %d, %Y")
        except ValueError:
            return None

    def _parse_changelog(self, html: str) -> Optional[Tuple[str, List[ScrapedFirmware]]]:
        soup = self.parse_html(html)
        title = next((self.TITLE.match(self._text(h2)) for h2 in soup.find_all("h2")
                      if self.TITLE.match(self._text(h2))), None)
        if not title:
            return None
        releases: List[ScrapedFirmware] = []
        for heading in soup.find_all("h3"):
            version = self.VERSION.match(self._text(heading))
            if not version:
                continue
            entry = heading.parent
            stamp = entry.find("small")
            notes = [self._own_text(item) if item.name == "li" else self._text(item)
                     for item in entry.find_all(["p", "li"])]
            releases.append(ScrapedFirmware(
                version=version.group("version"),
                release_date=self._parse_date(self._text(stamp)) if stamp else None,
                changelog="\n".join(note for note in notes if note)[: self.NOTES_LIMIT] or None,
            ))
        return (title.group("name"), releases) if releases else None

    # --- loading ------------------------------------------------------------

    async def _load(self) -> Optional[Dict[str, Tuple[str, List[ScrapedFirmware]]]]:
        if self._devices is not None:
            return self._devices
        downloads = await self.fetch_page(self.DOWNLOADS_URL)
        devices: Dict[str, Tuple[str, List[ScrapedFirmware]]] = {}
        for url in self._parse_downloads(downloads) if downloads else []:
            html = await self.fetch_page(url)
            parsed = self._parse_changelog(html) if html else None
            if parsed is None:
                logger.warning("oeksound change log %s did not load or listed no release", url)
                continue
            devices.setdefault(parsed[0], (url, parsed[1]))
        self._devices = devices or None
        return self._devices

    async def fetch_device_list(self) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error="No oeksound change log could be read")
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
            return ScraperResult(success=False, error="No oeksound change log could be read")
        entry = devices.get(device_name)
        return ScraperResult(success=True, firmware_versions=entry[1] if entry else [])
