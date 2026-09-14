import logging
import re
from typing import Dict, List, Optional, Tuple

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class TokyoDawnScraper(BaseScraper):
    """Tokyo Dawn Labs -- TDR Nova, Kotelnikov, SlickEQ and the rest, free and GE.

    Every product has one page, and every page carries its whole history: the
    current version beside the download buttons, and a changelog hidden behind a
    "(Changelog)" link that lists every release back to 1.0.0.

        <p class="margintop">Latest version: <strong>2.2.2</strong>
        <div class="changelogcontent" style="display: none">2.2.2 Hotfix<br/><br/>
            # Fixed a bug affecting host undo history<br/><br/><br/>2.2.1 Maintenance update<br/>...

    Each changelog entry is a line that starts with the version, followed by note
    lines that start with "#". Nothing on the page is dated, so no version is.

    Products are the `/tdr-*` links on the Tokyo Dawn Labs page. Two of them are
    bundles, with no version or changelog of their own, and are not listed. The GE
    ("Gentleman's Edition") releases are separate products with their own version
    numbers -- Kotelnikov GE is on 1.6.5 while the free Kotelnikov is on 1.6.7 -- so
    each is its own device. TDR Collector is Tokyo Dawn's library manager rather than
    a plug-in, and is catalogued under "other".

    The download links carry the version too (`/labs/Nova/2.2.2/TDR Nova.zip`) and
    are preferred over the "Latest version" text when the two disagree. A current
    version missing from the changelog is added to the top of it, without notes.
    """

    manufacturer_name = "Tokyo Dawn Labs"
    manufacturer_slug = "tokyodawn"
    manufacturer_website = "https://www.tokyodawn.net"

    LABS_URL = "https://www.tokyodawn.net/tokyo-dawn-labs/"
    # //www.tokyodawn.net/tdr-collector/, https://www.tokyodawn.net/tdr-nova/, http://...
    PRODUCT_LINK = re.compile(r"^(?:https?:)?//www\.tokyodawn\.net/(tdr-[a-z0-9-]+)/?$")
    ENTRY = re.compile(r"^(\d+(?:\.\d+)+)\b")
    DOWNLOAD = re.compile(r"/labs/[^/]+/(\d+(?:\.\d+)+)/")
    NOT_PLUGINS = {"tdr-collector"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._products: Optional[Dict[str, Tuple[str, str, List[ScrapedFirmware]]]] = None

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(part) for part in version.split("."))

    def _parse_changelog(self, block) -> List[ScrapedFirmware]:
        """Each entry is a line starting with its version; the "#" lines below are its notes."""
        entries: List[Tuple[str, List[str]]] = []
        for line in (" ".join(raw.split()) for raw in block.get_text("\n").split("\n")):
            if not line:
                continue
            entry = self.ENTRY.match(line)
            if entry:
                entries.append((entry.group(1), []))
            elif entries:
                entries[-1][1].append(line)

        versions: List[ScrapedFirmware] = []
        seen = set()
        for version, notes in entries:
            if version not in seen:
                seen.add(version)
                versions.append(ScrapedFirmware(version=version, changelog="\n".join(notes) or None))
        return versions

    def _parse_product(self, html: str) -> Tuple[Optional[str], List[ScrapedFirmware]]:
        soup = self.parse_html(html)
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        name = " ".join(title.split("|")[0].split()) or None

        stated = None
        label = soup.find(string=re.compile(r"Latest version"))
        if label is not None and label.parent is not None:
            strong = label.parent.find("strong")
            if strong is not None and re.fullmatch(r"\d+(?:\.\d+)+", strong.get_text(strip=True)):
                stated = strong.get_text(strip=True)

        built = {m.group(1) for a in soup.find_all("a", href=True) if (m := self.DOWNLOAD.search(a["href"]))}
        current = max(built, key=self._version_key) if built else stated

        block = soup.select_one("div.changelogcontent")
        versions = self._parse_changelog(block) if block is not None else []

        if current and current not in {fw.version for fw in versions}:
            if stated and built and stated != current:
                logger.info("TDR %s says %s, its downloads say %s; keeping the downloads", name, stated, current)
            versions.insert(0, ScrapedFirmware(version=current))
        return name, versions

    async def _load(self) -> Optional[Dict[str, Tuple[str, str, List[ScrapedFirmware]]]]:
        if self._products is not None:
            return self._products

        labs = await self.fetch_page(self.LABS_URL)
        if not labs:
            return None
        slugs = list(dict.fromkeys(
            m.group(1) for a in self.parse_html(labs).find_all("a", href=True)
            if (m := self.PRODUCT_LINK.match(a["href"].strip()))
        ))
        if not slugs:
            return None

        products: Dict[str, Tuple[str, str, List[ScrapedFirmware]]] = {}
        for slug in slugs:
            url = f"{self.manufacturer_website}/{slug}/"
            html = await self.fetch_page(url)
            if not html:
                logger.warning("TDR product page %s did not load", url)
                return None
            name, versions = self._parse_product(html)
            if not name or not versions:
                logger.info("TDR %s has no version of its own (a bundle); not listed", slug)
                continue
            category = "other" if slug in self.NOT_PLUGINS else "vst_plugin"
            products[name] = (url, category, versions)

        self._products = products
        return products

    async def fetch_device_list(self) -> ScraperResult:
        products = await self._load()
        if not products:
            return ScraperResult(success=False, error=f"No TDR products with a version found from {self.LABS_URL}")
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(name=name, category=category, firmware_page_url=url, product_url=url)
                for name, (url, category, _versions) in products.items()
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        products = await self._load()
        if not products:
            return ScraperResult(success=False, error=f"No TDR products with a version found from {self.LABS_URL}")
        if device_name not in products:
            return ScraperResult(success=True, firmware_versions=[])
        return ScraperResult(success=True, firmware_versions=list(products[device_name][2]))
