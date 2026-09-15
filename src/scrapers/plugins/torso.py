import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class TorsoScraper(BaseScraper):
    """Torso Electronics -- T-1 and S-4 firmware, every release dated, from the documentation site's changelogs.

    torsoelectronics.com renders its support pages in the browser and names no version
    (the S-4 download is ``S-4-OS-latest.zip``). docs.torsoelectronics.com is a static
    Docusaurus site with a changelog per product, discovered from the docs home page
    (``/t1/``, ``/s4/``; ``/ja/`` is the Japanese translation):

        <h2 id="v215">v2.1.5<a class="hash-link">&#8203;</a></h2><p><strong>Aug 5, 2026</strong></p>
        <h3>Bugfixes</h3><ul><li>Fixed an issue where <strong>TEMP + SAVE</strong> ...</li></ul>

    **Headings are written two ways**: T-1 as "v2.1.5", S-4 as "Changes in S4 OS v2.2.0",
    "S4 OS v2.1.3 Hotfix" and "S4 OS v2.0". The version is the ``v``-number in either.

    **Dates are typed by hand** -- "Aug 5, 2026", "December 18, 2025", and "December 16
    2025" without its comma. **One is out of order**: T-1 v2.0.2 says November 21, 2022,
    three weeks before v2.0.1 and v2.0.0 in December. Dates that disagree with version
    order are dropped by keeping the largest set that falls going down the log -- here
    that drops v2.0.2's alone rather than the two releases around it.

    Notes are each section's sub-headings and list items, one line per item, nested items
    on their own lines; the "Get the update at" sentence is not a note.
    """

    manufacturer_name = "Torso Electronics"
    manufacturer_slug = "torso"
    manufacturer_website = "https://torsoelectronics.com"

    DOCS_URL = "https://docs.torsoelectronics.com"
    PRODUCT_LINK = re.compile(r"^/(?P<slug>[a-z]\d+)/")
    VERSION = re.compile(r"\bv(?P<version>\d+(?:\.\d+)+)\b")
    DATE = re.compile(r"^(?P<month>[A-Za-z]{3})[a-z]*\.?\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})$")
    CATEGORIES = {"t1": "midi_controller"}
    NOTES_LIMIT = 4000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._devices: Optional[Dict[str, Tuple[str, str, List[ScrapedFirmware]]]] = None

    # --- parsing ------------------------------------------------------------

    @staticmethod
    def _text(element) -> str:
        return " ".join(element.get_text(" ").replace("​", "").split())

    @staticmethod
    def _name(slug: str) -> str:
        """t1 -> T-1, s4 -> S-4."""
        return re.sub(r"^([a-z]+)(\d+)$", lambda m: f"{m.group(1).upper()}-{m.group(2)}", slug)

    def _parse_home(self, html: str) -> List[str]:
        slugs: List[str] = []
        for link in self.parse_html(html).find_all("a", href=True):
            matched = self.PRODUCT_LINK.match(link["href"])
            if matched and matched.group("slug") not in slugs:
                slugs.append(matched.group("slug"))
        return slugs

    def _parse_date(self, text: str) -> Optional[datetime]:
        matched = self.DATE.match(text)
        if not matched:
            return None
        try:
            return datetime.strptime(f"{matched.group('month')} {matched.group('day')} {matched.group('year')}", "%b %d %Y")
        except ValueError:
            return None

    @staticmethod
    def _own_text(item) -> str:
        parts = [string for string in item.find_all(string=True)
                 if not any(parent.name in ("ul", "ol") for parent in string.parents
                            if parent is not item and item in parent.parents)]
        return " ".join(" ".join(parts).replace("​", "").split())

    @staticmethod
    def _keep_ordered_dates(releases: List[ScrapedFirmware]) -> None:
        """Drop dates that disagree with version order, keeping the largest set falling down the log."""
        dated = [i for i, release in enumerate(releases) if release.release_date]
        best: List[List[int]] = []
        for position, index in enumerate(dated):
            chain = [index]
            for earlier in range(position):
                candidate = best[earlier]
                if releases[candidate[-1]].release_date >= releases[index].release_date and len(candidate) + 1 > len(chain):
                    chain = candidate + [index]
            best.append(chain)
        keep = set(max(best, key=len)) if best else set()
        for index in dated:
            if index not in keep:
                releases[index].release_date = None

    def _parse_changelog(self, html: str) -> List[ScrapedFirmware]:
        releases: List[ScrapedFirmware] = []
        for heading in self.parse_html(html).find_all("h2"):
            matched = self.VERSION.search(self._text(heading))
            if not matched:
                continue
            date: Optional[datetime] = None
            lines: List[str] = []
            for element in heading.find_next_siblings():
                if element.name == "h2":
                    break
                if element.name == "p" and date is None and not lines:
                    date = self._parse_date(self._text(element))
                elif element.name in ("h3", "h4"):
                    lines.append(self._text(element))
                elif element.name in ("ul", "ol"):
                    lines.extend(self._own_text(item) for item in element.find_all("li"))
            releases.append(ScrapedFirmware(version=matched.group("version"), release_date=date,
                                            changelog="\n".join(l for l in lines if l)[: self.NOTES_LIMIT] or None))
        self._keep_ordered_dates(releases)
        return releases

    # --- loading ------------------------------------------------------------

    async def _load(self) -> Optional[Dict[str, Tuple[str, str, List[ScrapedFirmware]]]]:
        if self._devices is not None:
            return self._devices
        home = await self.fetch_page(self.DOCS_URL + "/")
        devices: Dict[str, Tuple[str, str, List[ScrapedFirmware]]] = {}
        for slug in self._parse_home(home) if home else []:
            url = f"{self.DOCS_URL}/{slug}/changelog/"
            html = await self.fetch_page(url)
            releases = self._parse_changelog(html) if html else []
            if not releases:
                logger.warning("Torso changelog %s did not load or listed no release", url)
                continue
            devices[self._name(slug)] = (url, self.CATEGORIES.get(slug, "synthesizer"), releases)
        self._devices = devices or None
        return self._devices

    async def fetch_device_list(self) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error="No Torso changelog could be read")
        return ScraperResult(
            success=True,
            devices=[ScrapedDevice(name=name, category=category, firmware_page_url=url, product_url=url)
                     for name, (url, category, _releases) in devices.items()],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error="No Torso changelog could be read")
        entry = devices.get(device_name)
        return ScraperResult(success=True, firmware_versions=entry[2] if entry else [])
