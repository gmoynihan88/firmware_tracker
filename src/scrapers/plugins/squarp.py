import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class SquarpScraper(BaseScraper):
    """Squarp Instruments -- Hapax, Hermod+, Rample, and the legacy Pyramid and Hermod, every OS release dated.

    squarp.net (not squarp.com, a different site) gives each product a firmware page,
    linked from the home page (``/hapax/firmware/``) or from ``/legacy/``
    (``/legacy/pyramid/firmware/``). Each lists every release, newest first:

        <div class="Headline"><p class="Headline_grey">HapaxOS 3.20<br/>
          <span class="smallfont">September 10, 2026<br/></span></p>
          <div class="mini_Text_grey">New features<ul><li>...</li></ul></div>
          <p><a class="downloadOS" href="/hapaxOS/3.20/hapax.bin">Download HapaxOS 3.20</a></p>

    **Name the product from its URL, not its OS.** The pages say "PyraOS" for Pyramid and
    "rampleOS" in lower case; the path segment before ``/firmware/`` is the product.

    **Dates are hand-typed**: "September 10, 2026", "Feb 27, 2026", "February 03, 2025",
    "27 January 2020", and the legacy pages in lower case ("october 29, 2019"). A month is
    read by its first three letters, with the day on either side of it.

    **Versions are kept as written.** Hermod has both "1.7" and "1.021", and Rample "1.4"
    beside "1.41"; they are the vendor's numbers, not padded.

    **A release's notes are the first text block after its heading**, which is sometimes
    preceded by an embedded video; the heading's own date span is not part of the version.
    """

    manufacturer_name = "Squarp Instruments"
    manufacturer_slug = "squarp"
    manufacturer_website = "https://squarp.net"

    BASE_URL = "https://squarp.net"
    LEGACY_URL = BASE_URL + "/legacy/"
    FIRMWARE_PAGE = re.compile(r"^(?:https?://squarp\.net)?/(?:legacy/)?(?P<slug>[a-z0-9-]+)/firmware/?$")
    HEADLINE = re.compile(r"^(?P<os>\S+?)\s*OS\s+v?(?P<version>\d+(?:\.\d+)+)$", re.I)
    DATE = re.compile(
        r"^(?:(?P<month>[A-Za-z]{3})[a-z]*\.?\s+(?P<day>\d{1,2}),?\s+|(?P<day2>\d{1,2})\s+(?P<month2>[A-Za-z]{3})[a-z]*\s+)"
        r"(?P<year>\d{4})$"
    )
    NAMES = {"hermodplus": "Hermod+"}
    CATEGORIES = {"rample": "synthesizer"}
    NOTES_LIMIT = 4000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._devices: Optional[Dict[str, Tuple[str, List[ScrapedFirmware]]]] = None

    # --- parsing ------------------------------------------------------------

    @staticmethod
    def _text(element) -> str:
        return " ".join(element.get_text(" ").split())

    def _parse_links(self, html: str) -> List[Tuple[str, str]]:
        """(product slug, firmware page URL) for every firmware page a page links."""
        pages: List[Tuple[str, str]] = []
        for link in self.parse_html(html).find_all("a", href=True):
            matched = self.FIRMWARE_PAGE.match(link["href"])
            if matched:
                entry = (matched.group("slug"), urljoin(self.BASE_URL, link["href"]))
                if entry[0] not in {slug for slug, _url in pages}:
                    pages.append(entry)
        return pages

    def _parse_date(self, text: str) -> Optional[datetime]:
        matched = self.DATE.match(" ".join(text.split()))
        if not matched:
            return None
        month = matched.group("month") or matched.group("month2")
        day = matched.group("day") or matched.group("day2")
        try:
            return datetime.strptime(f"{month} {day} {matched.group('year')}", "%b %d %Y")
        except ValueError:
            return None

    def _parse_page(self, html: str) -> List[ScrapedFirmware]:
        releases: List[ScrapedFirmware] = []
        for heading in self.parse_html(html).select("p.Headline_grey"):
            stamp = heading.select_one(".smallfont")
            date = self._parse_date(self._text(stamp)) if stamp else None
            if stamp:
                stamp.extract()
            matched = self.HEADLINE.match(self._text(heading))
            if not matched:
                continue
            notes = None
            for element in heading.find_all_next():
                if element.name == "p" and "Headline_grey" in (element.get("class") or []):
                    break
                if element.name == "div" and "mini_Text_grey" in (element.get("class") or []):
                    notes = element
                    break
            lines = [" ".join(line.split()) for line in notes.get_text("\n").splitlines()] if notes else []
            releases.append(ScrapedFirmware(
                version=matched.group("version"), release_date=date,
                changelog="\n".join(line for line in lines if line)[: self.NOTES_LIMIT] or None,
            ))
        return releases

    # --- loading ------------------------------------------------------------

    async def _load(self) -> Optional[Dict[str, Tuple[str, List[ScrapedFirmware]]]]:
        if self._devices is not None:
            return self._devices
        home = await self.fetch_page(self.BASE_URL + "/")
        if not home:
            return None
        pages = self._parse_links(home)
        legacy = await self.fetch_page(self.LEGACY_URL)
        if not legacy:
            logger.warning("Squarp legacy page did not load; legacy products not read")
        for slug, url in self._parse_links(legacy) if legacy else []:
            if slug not in {known for known, _url in pages}:
                pages.append((slug, url))
        devices: Dict[str, Tuple[str, List[ScrapedFirmware]]] = {}
        for slug, url in pages:
            html = await self.fetch_page(url)
            releases = self._parse_page(html) if html else []
            if not releases:
                logger.warning("Squarp firmware page %s did not load or listed no release", url)
                continue
            devices[slug] = (url, releases)
        self._devices = devices or None
        return self._devices

    def _name(self, slug: str) -> str:
        return self.NAMES.get(slug, slug.replace("-", " ").title())

    async def fetch_device_list(self) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error="No Squarp firmware page could be read")
        return ScraperResult(
            success=True,
            devices=[ScrapedDevice(name=self._name(slug), category=self.CATEGORIES.get(slug, "midi_controller"),
                                   firmware_page_url=url, product_url=url)
                     for slug, (url, _releases) in devices.items()],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error="No Squarp firmware page could be read")
        entry = next((entry for slug, entry in devices.items() if self._name(slug) == device_name), None)
        return ScraperResult(success=True, firmware_versions=entry[1] if entry else [])
