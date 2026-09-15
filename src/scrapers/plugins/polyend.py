import logging
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class PolyendScraper(BaseScraper):
    """Polyend -- firmware for every instrument whose downloads page carries a changelog.

    `/downloads/` links one downloads page per product, 19 of them. The firmware item on
    each carries its whole changelog, newest first, as plain server-rendered markup:

        <div class="changelog__version">
          <div class="changelog__version__number">1.6.0</div>
          <div class="changelog__version__title">Changes from 1.5.0 to 1.6.0</div>
          <div class="changelog__version__content"><h3>NEW FEATURES</h3><ul>...</ul></div>

    **No date is published** anywhere on the pages, checked on all 19 on 2026-09-14;
    every version is stored undated.

    **Not every page is an instrument's firmware.** Endless, Press, Anywhere and Perc
    publish manuals and presets but no changelog, and are not listed. Polyend Tool is
    the desktop companion app for the Tracker, not an instrument, and is left out the
    way editor apps are elsewhere.

    **Colour variants are one device.** Tracker Mini Aluminum (Black) and (Silver) have
    pages of their own carrying Tracker Mini's changelog and file. Pages whose
    changelogs are identical collapse into the shortest name.

    **A beta is not a release.** Tracker+ and Play+ keep "1.0.1 Beta" in their history.

    **One page can carry a changelog twice** -- Step lists it under two items -- so each
    version is taken once.

    Names get the brand, the way Polyend's own files do (`PolyendPlay_v1.6.0`): "Play"
    and "Step" alone read as words, not products. Categories follow Polyend's own menu:
    Mess and Step are guitar pedals, Seq and Preset MIDI tools, Poly2 a MIDI-to-CV
    converter, the rest synthesizers and grooveboxes.
    """

    manufacturer_name = "Polyend"
    manufacturer_slug = "polyend"
    manufacturer_website = "https://polyend.com"

    BASE_URL = "https://polyend.com"
    LISTING_URL = BASE_URL + "/downloads/"
    PAGE = re.compile(r"^(?:https?://(?:www\.)?polyend\.com)?/downloads/[^/]+-downloads/?$")
    NOT_INSTRUMENTS = {"Polyend Tool"}
    CATEGORIES = {"Mess": "guitar_pedal", "Step": "guitar_pedal", "Seq": "midi_controller",
                  "Preset": "midi_controller", "Poly2": "other"}
    VERSION = re.compile(r"^\d+(?:\.\d+)*$")
    NOTES_LIMIT = 4000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._devices: Optional[Dict[str, Tuple[str, List[ScrapedFirmware]]]] = None

    # --- parsing ------------------------------------------------------------

    def _parse_listing(self, html: str) -> List[str]:
        urls: List[str] = []
        for link in self.parse_html(html).find_all("a", href=True):
            href = link["href"].split("#")[0].split("?")[0]
            if self.PAGE.match(href):
                url = urljoin(self.BASE_URL, href.rstrip("/") + "/")
                if url not in urls:
                    urls.append(url)
        return urls

    @staticmethod
    def _text(element) -> str:
        return " ".join(element.get_text(" ").split()) if element else ""

    def _parse_page(self, html: str) -> Optional[Tuple[str, List[ScrapedFirmware]]]:
        soup = self.parse_html(html)
        name = re.sub(r"\s+downloads$", "", self._text(soup.find("h1")), flags=re.I).strip()
        if not name:
            return None

        versions: Dict[str, ScrapedFirmware] = {}
        for entry in soup.select(".changelog__version"):
            number = self._text(entry.select_one(".changelog__version__number"))
            if not self.VERSION.match(number) or number in versions:
                continue  # "1.0.1 Beta", or a changelog repeated under a second item
            title = self._text(entry.select_one(".changelog__version__title"))
            content = entry.select_one(".changelog__version__content")
            lines = [line.strip() for line in (content.get_text("\n") if content else "").split("\n") if line.strip()]
            versions[number] = ScrapedFirmware(
                version=number, release_date=None,
                changelog="\n".join([title, *lines] if title else lines)[: self.NOTES_LIMIT] or None,
            )
        if not versions:
            return None
        return name, list(versions.values())

    # --- loading ------------------------------------------------------------

    async def _load(self) -> Optional[Dict[str, Tuple[str, List[ScrapedFirmware]]]]:
        if self._devices is not None:
            return self._devices
        listing = await self.fetch_page(self.LISTING_URL)
        pages = self._parse_listing(listing) if listing else []

        by_changelog: Dict[Tuple[str, ...], Tuple[str, str, List[ScrapedFirmware]]] = {}
        for url in pages:
            html = await self.fetch_page(url)
            parsed = self._parse_page(html) if html else None
            if parsed is None:
                if not html:
                    logger.warning("Polyend downloads page %s did not load", url)
                continue
            name, versions = parsed
            key = tuple(f"{fw.version}\n{fw.changelog}" for fw in versions)
            known = by_changelog.get(key)
            if known is None or len(name) < len(known[0]):
                by_changelog[key] = (name, url, versions)  # a colour variant yields to the base product

        devices: Dict[str, Tuple[str, List[ScrapedFirmware]]] = {}
        for name, url, versions in by_changelog.values():
            branded = name if name.lower().startswith("polyend") else f"Polyend {name}"
            if branded in self.NOT_INSTRUMENTS:
                continue
            devices[branded] = (url, versions)
        self._devices = devices or None
        return self._devices

    def _category(self, device_name: str) -> str:
        return self.CATEGORIES.get(re.sub(r"^Polyend\s+", "", device_name), "synthesizer")

    async def fetch_device_list(self) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error=f"No Polyend changelogs found from {self.LISTING_URL}")
        return ScraperResult(
            success=True,
            devices=[ScrapedDevice(name=name, category=self._category(name), firmware_page_url=url, product_url=url)
                     for name, (url, _versions) in devices.items()],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error=f"No Polyend changelogs found from {self.LISTING_URL}")
        _url, versions = devices.get(device_name, (None, []))
        return ScraperResult(success=True, firmware_versions=list(versions))
