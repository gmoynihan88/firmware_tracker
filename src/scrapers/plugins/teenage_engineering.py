import re
import unicodedata
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class TeenageEngineeringScraper(BaseScraper):
    """Teenage Engineering, read from the downloads index and each product's page.

    `/downloads` links every product that has anything to download, and each
    `/downloads/<slug>` carries that product's whole OS history with dates:

        1.1.33    2026.09.02    click to download
        1.1.32    2026.09.01    click to download

    Thirteen fetches for 78 dated versions, which is cheap. Dates are the reason the
    product pages are read at all -- the index shows only the current version and no
    date, so stopping there would cost every release its date.

    **Version and date are paired by adjacency, not by container.** The markup differs
    between products: OP-XY puts both in one `div.bxl`, while EP-133 and EP-40 put
    them in separate elements, and a selector written against either one silently
    halves the catalogue. What holds everywhere is that the date immediately follows
    its version, so a line that is *entirely* a version followed by a line that is
    *entirely* a date is a release.

    Requiring both to be whole lines is what keeps the changelogs out. The notes below
    each release say things like "OS 2.0.2" and "support for 2.0", which a search
    would collect; neither is a bare line. It also excludes the oplab module, whose
    markup splits "1.1.1" across elements so no line is a complete version -- one
    accessory, left out rather than given a pattern of its own.

    **Names use an en dash.** The site writes OP–XY, EP–133 and TP–7 with U+2013,
    which nobody types and which would create a second row beside a user's "OP-XY".
    `_normalise_name` converts it, the same normalisation Focusrite's superscript plus
    and Oberheim's trademark symbol needed.

    Products deliberately absent:

    - **PO-32 and PO-33.** Pocket Operators take no firmware; their pages describe
      loading sounds over audio, not updating an OS. Listing them would add rows that
      can never report a version.
    - **The sound-pack pages** under each product, which are content.
    - **usb-asio**, a driver rather than an instrument.

    OP-1 is included and reports 1.7.3 with no date: it is discontinued, its page
    lists one version and no history, and that is the honest reading rather than a
    parse that failed.
    """

    manufacturer_name = "Teenage Engineering"
    manufacturer_slug = "teenageengineering"
    manufacturer_website = "https://teenage.engineering"

    INDEX_URL = "https://teenage.engineering/downloads"

    # Pages under /downloads/ that do not yield a product's OS.
    #
    # oplab-module is the odd one: it has firmware, and its markup splits "1.1.1"
    # across elements so no line is a complete version. Rather than give one
    # accessory a pattern of its own, it is left out -- a row that can never report
    # a version is the Focusrite failure, and this would be a self-inflicted one.
    NOT_A_PRODUCT = ("/sound-packs", "/usb-asio", "/oplab-module")

    # Pocket Operators have no updatable firmware, so they are left out rather than
    # added as permanent blanks. See the class docstring.
    NO_FIRMWARE_SLUGS = {"po-32", "po-33"}

    # A whole line that is nothing but a version, and one that is nothing but a date.
    VERSION_LINE = re.compile(r"\d+(?:\.\d+)+")
    DATE_LINE = re.compile(r"(\d{4})\.(\d{2})\.(\d{2})")

    # Display names on the index, so the catalogue reads as the vendor writes it.
    CATEGORY_BY_SLUG = {
        "op-xy": "synthesizer",
        "op-z": "synthesizer",
        "op-1": "synthesizer",
        "ep-133": "synthesizer",
        "ep-1320": "synthesizer",
        "ep-136": "synthesizer",
        "ep-2350": "synthesizer",
        "ep-40": "synthesizer",
        "choir": "synthesizer",
        "tx-6": "audio_interface",
        "tp-7": "audio_interface",
        "cm-15": "other",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._products: Optional[List[Tuple[str, str]]] = None
        self._names: Dict[str, str] = {}

    @staticmethod
    def _normalise_name(name: str) -> str:
        """Convert the site's typography to what a person would type.

        OP–XY is written with an en dash. Left alone it creates a device row nobody
        can match against, which is how a scrape orphans the products a user already
        tracks.
        """
        name = unicodedata.normalize("NFKC", name)
        for dash in ("–", "—", "−"):
            name = name.replace(dash, "-")
        return " ".join(name.split())

    def _slug_name(self, slug: str) -> str:
        """Fallback when the index gives no display text for a product."""
        tail = slug.split("/")[-1]
        return "-".join(part.upper() if len(part) <= 3 else part.capitalize()
                        for part in tail.split("-"))

    def _index_products(self, html: str) -> List[Tuple[str, str]]:
        """(slug, display name) for every product the index links to."""
        soup = self.parse_html(html)

        # Names come from the rows that state a version, which are the only place the
        # index spells the product out.
        for anchor in soup.select("a.abox, a.lnk"):
            href = anchor.get("href") or ""
            if not href.startswith("/downloads/"):
                continue
            parts = anchor.get_text("|", strip=True).split("|")
            if parts and parts[0].strip():
                slug = href[len("/downloads/"):].strip("/")
                self._names.setdefault(slug, self._normalise_name(parts[0]))

        found: List[Tuple[str, str]] = []
        seen = set()
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            if not href.startswith("/downloads/"):
                continue
            if any(href.endswith(tail) for tail in self.NOT_A_PRODUCT):
                continue
            slug = href[len("/downloads/"):].strip("/")
            if not slug or slug in seen or slug in self.NO_FIRMWARE_SLUGS:
                continue
            seen.add(slug)
            found.append((slug, self._names.get(slug) or self._slug_name(slug)))

        return sorted(found)

    def _parse_product(self, html: str) -> List[ScrapedFirmware]:
        """Pair each version line with the date line directly below it."""
        text = re.sub(r"[ \t]+", " ", self.parse_html(html).get_text("\n"))
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        versions: List[ScrapedFirmware] = []
        seen = set()

        for index, line in enumerate(lines[:-1]):
            if not self.VERSION_LINE.fullmatch(line) or line in seen:
                continue
            dated = self.DATE_LINE.fullmatch(lines[index + 1])
            if not dated:
                continue
            seen.add(line)
            try:
                release_date = datetime(
                    int(dated.group(1)), int(dated.group(2)), int(dated.group(3))
                )
            except ValueError:
                release_date = None
            versions.append(ScrapedFirmware(version=line, release_date=release_date))

        if not versions:
            # OP-1 lists a current version with no date and no history. A version
            # line followed by anything else is still a version.
            for index, line in enumerate(lines[:-1]):
                if self.VERSION_LINE.fullmatch(line) and "update" in lines[index + 1].lower():
                    versions.append(ScrapedFirmware(version=line))
                    break

        return sorted(versions, key=lambda fw: self._version_key(fw.version), reverse=True)

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(part) for part in re.findall(r"\d+", version)) or (0,)

    async def _load_index(self) -> Optional[List[Tuple[str, str]]]:
        if self._products is not None:
            return self._products
        html = await self.fetch_page(self.INDEX_URL)
        if not html:
            return None
        products = self._index_products(html)
        if not products:
            return None
        self._products = products
        return products

    async def fetch_device_list(self) -> ScraperResult:
        products = await self._load_index()
        if products is None:
            return ScraperResult(
                success=False, error=f"Failed to read {self.INDEX_URL}"
            )

        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category=self.CATEGORY_BY_SLUG.get(slug, "other"),
                    firmware_page_url=urljoin(self.INDEX_URL + "/", slug),
                    product_url=urljoin(self.INDEX_URL + "/", slug),
                )
                for slug, name in products
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        html = await self.fetch_page(firmware_page_url)
        if not html:
            return ScraperResult(
                success=False, error=f"Failed to fetch {firmware_page_url}"
            )

        versions = self._parse_product(html)
        # An empty result is a real answer here: several accessories under /downloads
        # have a page and no OS.
        return ScraperResult(success=True, firmware_versions=versions)
