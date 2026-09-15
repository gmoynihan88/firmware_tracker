import re
from datetime import datetime
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class TascamScraper(BaseScraper):
    """Tascam hardware, read from the firmware tables on each product's support page.

    **The catalogue is the category pages.** The US home page links 21 of them
    ("audio_interface", "portable_handheld_field_recoder", ...), each lists twelve
    products a page, and each page after the first is `?paged=N`, linked from the one
    before. 146 products on 2026-09-15. Every product's support page is read while
    listing -- about three and a half minutes -- and the products listed are the 61
    whose page states a firmware version. Until then the list was nine, kept by
    hand.

    A support page states firmware twice:

        Latest version info             | Firmware        | V1.50
        Firmware / Software (documents) | Firmware V1.50  | 2025-06-25
                                        | Firmware V1.42  | 2024-06-05

    The first is the current version, undated; the second is the download history,
    dated. Both are read, and a current version the history does not list is kept.

    **Most rows that say firmware are not the product's release**, and the previous
    parser -- a scan of any row containing "firmware" and a V-number -- could not
    tell:

    - "Firmware update procedures", a PDF, carries a date of its own.
    - "Dante module firmware", "FPGA firmware", "Drive firmware", "Sub firmware" and
      "REC firmware" are components with their own numbering.
    - "IF-MTR32 : Firmware V1.12" is an expansion card's, on the console's page.
    - "DA-6400 firmware version | V1.30 or later" is an app's requirement.
    - A Blu-ray player's "206.2227 (Japan, USA)" is a build number.

    So the current version comes only from a row labelled exactly Firmware, System
    firmware or Main firmware, and a history row must begin with the word Firmware
    (optionally Main or System) followed by its version. The Sonicview series' pages
    all carry the same three latest-version tables -- the console's, the SB-16D I/O
    rack's and the IF-ST2110 card's -- so on a page with more than one, none is
    trusted: the first draft took the first table and gave SB-16D and IF-ST2110 the
    console's 2.3.4.

    Names come from the page title before " | ", with the brand dropped: "TASCAM
    Sonicview 16XP / TASCAM Sonicview 16dp" is "Sonicview 16XP / Sonicview 16dp".
    Tascam publishes no release notes in a readable form beside the files, so the
    changelog is left empty rather than filled with a row's label.
    """

    manufacturer_name = "Tascam"
    manufacturer_slug = "tascam"
    manufacturer_website = "https://tascam.com"

    HOME_URL = "https://tascam.com/us/"
    SUPPORT_URL = "https://tascam.com/us/product/{slug}/support"
    PRODUCT_URL = "https://tascam.com/us/product/{slug}"

    CATEGORY_LINK = re.compile(r"^https://tascam\.com/us/category/(?P<category>[a-z0-9_]+)/?$")
    PRODUCT_LINK = re.compile(r"^https://tascam\.com/us/product/(?P<slug>[^/?#]+)/?$")

    # A pager that never ran dry would otherwise walk forever. The longest category is
    # a few pages.
    MAX_CATEGORY_PAGES = 30

    CURRENT_LABELS = {"firmware", "system firmware", "main firmware"}
    LATEST_VERSION = re.compile(r"^V(?P<version>\d+(?:\.\d+)+)$")
    RELEASE_ROW = re.compile(r"^(?:(?:Main|System)\s+)?Firmware\s+V(?P<version>\d+(?:\.\d+)+)\b", re.I)
    DATE = re.compile(r"^(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})$")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._catalogue: Optional[Dict[str, dict]] = None

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(part) for part in re.findall(r"\d+", version)) or (0,)

    def _category_links(self, html: str) -> List[str]:
        links = []
        for anchor in self.parse_html(html).find_all("a", href=True):
            match = self.CATEGORY_LINK.match(anchor["href"])
            if match and match.group(0).rstrip("/") not in links:
                links.append(match.group(0).rstrip("/"))
        return links

    def _product_slugs(self, html: str) -> List[str]:
        slugs = []
        for anchor in self.parse_html(html).find_all("a", href=True):
            match = self.PRODUCT_LINK.match(anchor["href"])
            if match and match.group("slug") not in slugs:
                slugs.append(match.group("slug"))
        return slugs

    def _product_name(self, html: str) -> Optional[str]:
        title = self.parse_html(html).title
        if not title:
            return None
        name = title.get_text(" ", strip=True).split(" | ")[0]
        name = re.sub(r"\bTASCAM\s+", "", name).strip()
        return name or None

    def _current_version(self, soup) -> Optional[str]:
        """The page's own firmware from its latest-version table, when it has only one.

        The Sonicview series shares its latest-version tables across every unit's
        page: SB-16D's and IF-ST2110's pages both open with the console's "Firmware
        V2.3.4". With more than one table there is no telling which is the page's
        own, so none is used and the download history, which is per product, speaks
        for it.
        """
        tables = [
            table for table in soup.select("table.table-bordered")
            if any(
                cells and cells[0].lower() in self.CURRENT_LABELS
                for cells in (
                    [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
                    for row in table.find_all("tr")
                )
            )
        ]
        if len(tables) != 1:
            return None
        for row in tables[0].find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
            if len(cells) >= 2 and cells[0].lower() in self.CURRENT_LABELS:
                match = self.LATEST_VERSION.match(cells[1])
                return match.group("version") if match else None
        return None

    def _parse_support_page(self, html: str) -> List[ScrapedFirmware]:
        soup = self.parse_html(html)
        versions: Dict[str, ScrapedFirmware] = {}

        for table in soup.select("table.documents-table"):
            for row in table.find_all("tr"):
                label = row.find("th")
                if not label:
                    continue
                match = self.RELEASE_ROW.match(label.get_text(" ", strip=True))
                if not match or match.group("version") in versions:
                    # The Windows and macOS files of one release share its version.
                    continue

                release_date = None
                for cell in row.find_all("td"):
                    dated = self.DATE.match(cell.get_text(" ", strip=True))
                    if dated:
                        release_date = datetime(
                            int(dated.group("year")), int(dated.group("month")), int(dated.group("day"))
                        )
                        break

                link = label.find("a", href=True)
                versions[match.group("version")] = ScrapedFirmware(
                    version=match.group("version"),
                    release_date=release_date,
                    download_url=urljoin(self.HOME_URL, link["href"]) if link else None,
                )

        current = self._current_version(soup)
        if current and current not in versions:
            versions[current] = ScrapedFirmware(version=current)

        return sorted(versions.values(), key=lambda fw: self._version_key(fw.version), reverse=True)

    async def _load(self) -> Optional[Dict[str, dict]]:
        """Every product whose support page states firmware, read once per scrape."""
        if self._catalogue is not None:
            return self._catalogue

        home = await self.fetch_page(self.HOME_URL)
        categories = self._category_links(home) if home else []
        if not categories:
            return None

        products: Dict[str, Set[str]] = {}
        for category_url in categories:
            category = self.CATEGORY_LINK.match(category_url + "/").group("category")
            page = 1
            while page <= self.MAX_CATEGORY_PAGES:
                url = category_url if page == 1 else f"{category_url}?paged={page}"
                html = await self.fetch_page(url)
                if not html:
                    # A category page that fails would drop its products without a word.
                    return None
                for slug in self._product_slugs(html):
                    products.setdefault(slug, set()).add(category)
                if f"paged={page + 1}" not in html:
                    break
                page += 1

        if not products:
            return None

        catalogue: Dict[str, dict] = {}
        for slug, in_categories in products.items():
            url = self.SUPPORT_URL.format(slug=slug)
            html = await self.fetch_page(url)
            if not html:
                return None
            versions = self._parse_support_page(html)
            name = self._product_name(html)
            if versions and name:
                catalogue[name] = {
                    "slug": slug,
                    "url": url,
                    "versions": versions,
                    "category": "audio_interface" if "audio_interface" in in_categories else "other",
                }

        self._catalogue = catalogue
        return catalogue

    async def fetch_device_list(self) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(
                success=False, error=f"Could not read Tascam's catalogue from {self.HOME_URL}"
            )

        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category=entry["category"],
                    firmware_page_url=entry["url"],
                    product_url=self.PRODUCT_URL.format(slug=entry["slug"]),
                )
                for name, entry in catalogue.items()
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(
                success=False, error=f"Could not read Tascam's catalogue from {self.HOME_URL}"
            )

        entry = catalogue.get(device_name)
        # US-2x2HR's support page states no firmware; its row predates the catalogue.
        return ScraperResult(success=True, firmware_versions=entry["versions"] if entry else [])
