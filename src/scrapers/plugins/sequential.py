import logging
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class SequentialScraper(BaseScraper):
    """Sequential -- the Main OS of every synth with an operating-system page.

    `/support/download/` links one "Operating System" page per instrument, 22 of them,
    from the Evolver to the Trigon-6, beside documentation and sounds pages that carry
    no OS. Each page states the current version in prose and offers the update as a
    labelled download:

        The current version of the Prophet Rev2 OS is Main 1.2.5
        <a href=".../Rev2_OS_1.2.5.zip"><span>Operating System v1.2.5</span></a>

    **No page dates anything**, checked on all 22 on 2026-09-14, so every version is
    stored undated. The Oberheim instruments (OB-X8, OB-6, TEO-5) moved to oberheim.com
    and are not on this site.

    **The version is Main.** Most instruments run more than one OS -- Main with Voice,
    DSP, Panel or Keys -- and the page names them all. Main is the one the instrument's
    global menu reports and the one an update page leads with; the rest are components.
    The sentence naming Main is read first, and it is written a dozen ways: "The current
    Main operating system is version 2.2; DSP is version 3.4", "The current version of
    the Main OS is: Main 1.0.0.1", "The newest version of the Pro 3 Main OS is
    Pro3_Main_1.2.1.0", "The current operating system versions are Main 2.2, Voice 2.2".

    **The download label is second, because it can name a component.** Poly Evolver
    Rack's reads "Operating System v2.2" over `Poly_Evolver_Rack_OS_M2.1_V2.2_D3.5.zip` --
    2.2 is Voice; Main is 2.1. Fourm's download is the Keys update, 1.0.0.2, while Main
    is 1.0.0.1. Where no sentence names Main -- Prophet X, and Tempest, whose prose still
    calls 1.4 "the latest OS" beside a 1.5.0.2 download -- the label is read.

    **A beta is not the current version.** Take 5 offers "Poly Chain BETA OS v2.2.0.9"
    beside the released 2.1.0.2.

    The storefront's "$ 0.00" cart total sits in every page's header; only a sentence
    about a current version, or a download label, is read. A page that names no version
    either way is skipped with a warning rather than listed with nothing.
    """

    manufacturer_name = "Sequential"
    manufacturer_slug = "sequential"
    manufacturer_website = "https://sequential.com"

    BASE_URL = "https://sequential.com"
    LISTING_URL = BASE_URL + "/support/download/"
    OS_PAGE = re.compile(r"^(?:https?://(?:www\.)?sequential\.com)?/support/download/[^/]+-operating-system/?$")

    SENTENCE_END = re.compile(r"(?<!\d)\.(?!\d)|;|\n")
    CURRENT = re.compile(r"\b(?:current|latest|newest)\b", re.I)
    MAIN = re.compile(
        r"\bMain(?:\s+(?:operating\s+system|OS))?(?:\s+(?:is|version))*\s*:?\s*"
        r"(?:[\w-]*_Main_)?(?:Main\s+)?v?(?P<version>\d+(?:\.\d+)+)")
    LABEL = re.compile(r"^Operating\s+System\s+v?\.?\s*(?P<version>\d+(?:\.\d+)+)", re.I)
    TITLE_SUFFIX = re.compile(r"\s+Operating\s+System(?:\s*[-|–]\s*Sequential)?\s*$", re.I)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._devices: Optional[Dict[str, Tuple[str, ScrapedFirmware]]] = None

    # --- parsing ------------------------------------------------------------

    def _parse_listing(self, html: str) -> List[str]:
        urls: List[str] = []
        for link in self.parse_html(html).find_all("a", href=True):
            href = link["href"].split("#")[0].split("?")[0]
            if self.OS_PAGE.match(href):
                url = urljoin(self.BASE_URL, href)
                if url not in urls:
                    urls.append(url)
        return urls

    def _main_version(self, text: str) -> Optional[Tuple[str, str]]:
        """(version, sentence) from the first sentence about a current version that names Main."""
        for sentence in self.SENTENCE_END.split(" ".join(text.split())):
            if not self.CURRENT.search(sentence):
                continue
            matched = self.MAIN.search(sentence)
            if matched:
                return matched.group("version"), sentence.strip()
        return None

    def _parse_page(self, html: str) -> Optional[Tuple[str, ScrapedFirmware]]:
        soup = self.parse_html(html)
        title_tag = soup.find("title") or soup.find("h1")
        name = self.TITLE_SUFFIX.sub("", " ".join(title_tag.get_text(" ").split())) if title_tag else ""
        if not name:
            return None

        downloads = [(" ".join(a.get_text(" ").split()), a["href"]) for a in soup.find_all("a", href=True)]
        release = next(((label, href) for label, href in downloads
                        if self.LABEL.match(label) and "beta" not in (label + href).lower()), None)

        stated = self._main_version(soup.get_text(" "))
        if stated:
            version, notes = stated
        elif release:
            version, notes = self.LABEL.match(release[0]).group("version"), release[0]
        else:
            return None
        return name, ScrapedFirmware(
            version=version, release_date=None,
            download_url=urljoin(self.BASE_URL, release[1]) if release else None,
            changelog=notes[:300],
        )

    # --- loading ------------------------------------------------------------

    async def _load(self) -> Optional[Dict[str, Tuple[str, ScrapedFirmware]]]:
        if self._devices is not None:
            return self._devices
        listing = await self.fetch_page(self.LISTING_URL)
        pages = self._parse_listing(listing) if listing else []
        devices: Dict[str, Tuple[str, ScrapedFirmware]] = {}
        for url in pages:
            html = await self.fetch_page(url)
            parsed = self._parse_page(html) if html else None
            if parsed is None:
                logger.warning("Sequential OS page %s did not load or named no version", url)
                continue
            name, firmware = parsed
            devices.setdefault(name, (url, firmware))
        self._devices = devices or None
        return self._devices

    async def fetch_device_list(self) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error=f"No Sequential OS versions found from {self.LISTING_URL}")
        return ScraperResult(
            success=True,
            devices=[ScrapedDevice(name=name, category="synthesizer", firmware_page_url=url, product_url=url)
                     for name, (url, _firmware) in devices.items()],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error=f"No Sequential OS versions found from {self.LISTING_URL}")
        entry = devices.get(device_name)
        return ScraperResult(success=True, firmware_versions=[entry[1]] if entry else [])
