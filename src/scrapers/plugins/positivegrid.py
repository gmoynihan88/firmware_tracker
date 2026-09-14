import json
import logging
import re
from datetime import datetime
from typing import Dict, Iterator, List, Optional, Tuple

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class PositiveGridScraper(BaseScraper):
    """Positive Grid -- BIAS FX 2, BIAS AMP 2, BIAS Pedal, BIAS X, and the Spark amps.

    Every product with releases has a release-notes article in Positive Grid's
    Zendesk Help Center, and the Help Center API answers without a login. One search
    for "release notes" returns all of them, bodies included, in a few pages:

        help.positivegrid.com/api/v2/help_center/articles/search.json?query=release%20notes

    **Which articles are products.** Titles decide it:

    - "<name> Firmware Release Note(s)" is hardware: the Spark amps, Spark PEDAL,
      Spark Control X, BIAS MINI, BIAS Head/Rack, REACTOR.
    - "BIAS <name> [Desktop] Update History / Release Notes" is a plug-in: BIAS FX 2,
      BIAS AMP 2, BIAS Pedal, the first-generation BIAS FX and BIAS Amp, and BIAS X.
    - Everything else is left out: the BIAS mobile apps, the Spark and REACTOR apps,
      JamUp, Final Touch and X Drummer are apps rather than plug-ins or firmware.

    REACTOR 50/100's article says no firmware has been released yet, so it has no
    release to list and is not catalogued until it does.

    **Reading an article.** A release is a line naming its version, with the date --
    when there is one -- on the line above it and the notes below:

        <p><strong>Jan 16, 2025</strong></p>
        <p><strong>Spark GO firmware ver. 1.15.0.209</strong></p>
        <ul><li>Headphone output optimized...</li></ul>

    The heading is written three ways, and the BIAS Amp article once as "Changed in":

        Changes in BIAS FX 2 Desktop 2.7.0.6600
        Spark 2 firmware ver. 2.7.2.200 / rev490
        Spark MINI firmware v1.10.2.57 (Bluetooth Firmware v1.90)
        BIAS X ver. 1.2.4

    and the date six ways: "3/16/2021", "08/31/2023", "11.8.2019", "July 15. 2024",
    "Mar 31, 2025", "August 19, 2026". Spark Control X's date is bold text outside any paragraph, so
    bare bold text between blocks is read too. A date belongs only to the heading
    directly below it: Spark PEDAL's factory firmware sits under "Factory Version",
    not under the date of the release above it.

    **The notes name versions of their own**, and a heading must match in full to
    count: 'Fixed "BIAS FX v1.6.8 crashes Pro Tools"', "Updated bundled BIAS GEAR
    firmware to 0.5.2.193", "(for units shipped with firmware version 0.1.2.197)".

    **Versions are kept as Positive Grid writes them**, build number included
    (1.10.8.25): that is the form its apps and support articles use to say which
    firmware is required. The "/ rev490" hardware revision is not part of it.

    **Spark MINI lists 1.11.2.75 twice**: the firmware in May 2024, then again in
    March 2026 beside a Bluetooth-only update. It is one version, dated by its first
    release, with both sets of notes.

    Older BIAS desktop releases were never dated in these articles -- BIAS AMP 2 and
    BIAS Pedal carry dates only from 2020, and the first-generation plug-ins none.
    Amps are catalogued as guitar pedals, following Fender's Tone Master and Yamaha's
    THR: the category enum has no amplifier.
    """

    manufacturer_name = "Positive Grid"
    manufacturer_slug = "positivegrid"
    manufacturer_website = "https://www.positivegrid.com"

    SEARCH_URL = (
        "https://help.positivegrid.com/api/v2/help_center/articles/search.json"
        "?query=release%20notes&per_page=100"
    )
    MAX_PAGES = 5
    # Fewer than this many release-note articles means the search broke, not that
    # Positive Grid withdrew most of its products.
    MIN_ARTICLES = 10

    HARDWARE_TITLE = re.compile(r"^(?P<name>.+?)\s+Firmware\s+Release\s+Notes?$", re.I)
    PLUGIN_TITLE = re.compile(
        r"^(?P<name>BIAS\b.+?)(?:\s+Desktop)?\s+Update\s+History\s*[/&]\s*Release\s+Notes$", re.I
    )
    CATEGORIES = {"Spark Control X": "midi_controller"}

    _V = r"(?P<version>\d+(?:\.\d+)+)"
    HEADINGS = (
        re.compile(rf"^Change[sd]\s+in\s+.+?\s{_V}(?:\s*\(.*\))?$", re.I),
        re.compile(rf"^.+?\s+firmware\s+(?:ver\.?\s*|v)?{_V}(?:\s*/\s*rev\s*\d+)?(?:\s*\(.*\))?$", re.I),
        re.compile(rf"^.+?\s+ver\.\s*{_V}$", re.I),
    )
    # Month first throughout: "3/16/2021", "08/31/2023", and once "11.8.2019" between two slashed dates.
    DATE_NUMERIC = re.compile(r"^(\d{1,2})[/.](\d{1,2})[/.](\d{4})$")
    DATE_WORDS = re.compile(r"^([A-Za-z]+)\.?\s+(\d{1,2})[.,]?\s+(\d{4})$")

    BLOCKS = ("p", "h1", "h2", "h3", "h4", "h5", "h6", "div", "li")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._products: Optional[Dict[str, Tuple[str, str, List[ScrapedFirmware]]]] = None

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(part) for part in version.split("."))

    def _date(self, text: str) -> Optional[datetime]:
        numeric = self.DATE_NUMERIC.match(text)
        if numeric:
            month, day, year = (int(part) for part in numeric.groups())
            try:
                return datetime(year, month, day)
            except ValueError:
                return None
        words = self.DATE_WORDS.match(text)
        if words:
            for fmt in ("%B %d %Y", "%b %d %Y"):
                try:
                    return datetime.strptime(" ".join(words.groups()), fmt)
                except ValueError:
                    continue
        return None

    def _heading_version(self, text: str) -> Optional[str]:
        for pattern in self.HEADINGS:
            matched = pattern.match(text)
            if matched:
                return matched.group("version")
        return None

    def _lines(self, soup) -> Iterator[Tuple[str, str]]:
        """Innermost blocks in order, plus bold text left bare between blocks."""
        for element in soup.find_all(True):
            if element.name in self.BLOCKS:
                if element.find(self.BLOCKS) is None:
                    yield element.name, " ".join(element.get_text(" ").split())
            elif element.name in ("strong", "b") and element.find_parent(["strong", "b"]) is None:
                container = element.find_parent(self.BLOCKS)
                if container is None or container.find(self.BLOCKS) is not None:
                    yield "bold", " ".join(element.get_text(" ").split())

    def _parse_article(self, body: str) -> List[ScrapedFirmware]:
        releases: List[Tuple[str, Optional[datetime], List[str]]] = []
        pending: Optional[datetime] = None
        for kind, text in self._lines(self.parse_html(body or "<div></div>")):
            if not text:
                continue
            if kind != "li":
                date = self._date(text)
                if date is not None:
                    pending = date
                    continue
                version = self._heading_version(text)
                if version is not None:
                    releases.append((version, pending, []))
                    pending = None
                    continue
            # Anything else between a date and a heading means the date was not the heading's.
            pending = None
            if releases:
                releases[-1][2].append(f"- {text}" if kind == "li" else text)

        versions: Dict[str, ScrapedFirmware] = {}
        for version, released, notes in releases:
            changelog = "\n".join(notes) or None
            existing = versions.get(version)
            if existing is None:
                versions[version] = ScrapedFirmware(version=version, release_date=released, changelog=changelog)
                continue
            # Newest first, so a version repeated further down is its first release.
            if released and (existing.release_date is None or released < existing.release_date):
                existing.release_date = released
            if changelog:
                existing.changelog = "\n".join(filter(None, [existing.changelog, changelog]))
        return sorted(versions.values(), key=lambda fw: self._version_key(fw.version), reverse=True)

    def _product(self, title: str) -> Optional[Tuple[str, str]]:
        """(name, category) for a release-notes article that is a product, else None."""
        title = " ".join(title.split())
        hardware = self.HARDWARE_TITLE.match(title)
        plugin = None if hardware else self.PLUGIN_TITLE.match(title)
        matched = hardware or plugin
        if not matched:
            return None
        name = re.sub(r"\((\d+)\)", r"\1", matched.group("name")).strip()  # "Spark (40)"
        if plugin and re.search(r"\bmobile\b", name, re.I):
            return None
        category = "vst_plugin" if plugin else self.CATEGORIES.get(name, "guitar_pedal")
        return name, category

    async def _load(self) -> Optional[Dict[str, Tuple[str, str, List[ScrapedFirmware]]]]:
        if self._products is not None:
            return self._products

        articles: List[dict] = []
        url: Optional[str] = self.SEARCH_URL
        for _page in range(self.MAX_PAGES):
            if not url:
                break
            raw = await self.fetch_page(url)
            if not raw:
                return None
            try:
                data = json.loads(raw)
            except ValueError:
                return None
            articles.extend(data.get("results") or [])
            url = data.get("next_page")

        products: Dict[str, Tuple[str, str, List[ScrapedFirmware]]] = {}
        matched_articles = 0
        for article in articles:
            if article.get("locale", "en-us") != "en-us":
                continue
            product = self._product(article.get("title") or "")
            if product is None:
                continue
            matched_articles += 1
            name, category = product
            versions = self._parse_article(article.get("body") or "")
            if not versions:
                logger.info("Positive Grid %s lists no release yet; not catalogued", name)
                continue
            products.setdefault(name, (article.get("html_url") or self.manufacturer_website, category, versions))

        if matched_articles < self.MIN_ARTICLES:
            logger.warning("Positive Grid search matched %d release-note articles", matched_articles)
            return None
        self._products = products
        return products

    async def fetch_device_list(self) -> ScraperResult:
        products = await self._load()
        if not products:
            return ScraperResult(success=False, error="No Positive Grid release notes found in its Help Center")
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(name=name, category=category, firmware_page_url=url, product_url=url)
                for name, (url, category, _versions) in sorted(products.items())
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        products = await self._load()
        if not products:
            return ScraperResult(success=False, error="No Positive Grid release notes found in its Help Center")
        if device_name not in products:
            return ScraperResult(success=True, firmware_versions=[])
        return ScraperResult(success=True, firmware_versions=list(products[device_name][2]))
