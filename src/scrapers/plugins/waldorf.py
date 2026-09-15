import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class WaldorfScraper(BaseScraper):
    """Waldorf synths, from the Firmware section of each product's FAQ page.

    The FAQ index (/produkt-faq/) links one page per product, and each page ends in a row
    of download columns, each headed by an h2: "Manuals", "Firmware", "Other Downloads".
    A firmware download is a button whose text is its version:

        <h2>Firmware</h2> <a href=".../s/N9g8o8tojBTe6P8"><span>version 1.7.8</span></a>
                          <a href=".../s/bE2ZdPqq6gTmdpD"><span>Firmware manager win</span></a>

    **Only two products publish one**, as of 2026-09-15: Kyra (1.7.8) and STVC (1.30
    and 1.27). The share links behind them name the same files -- Kyra_Firmware_0178.zip,
    STVC_OS_V1.30.zip. Every other page has manuals only; "manual OS 2.0" in Quantum's
    Manuals column is a manual, not a release. Nothing on any page dates a release.

    Ruled out on 2026-09-15:
    - Iridium, Quantum and the other current synths: their updates are downloaded
      through a myWaldorf account, and the FAQ pages carry no version.
    - Blofeld: OS 1.25 HS is sent out by email on request.
    - Pulse 2: the "1.02 mac" on its page is the Spectre software.

    A product is listed only when its Firmware section has a version button, and its
    name comes from the page title, "FAQ Kyra EN – Waldorf Music". If Kyra's button stops
    reading as a version, Kyra drops out of the listing and its lookup fails, rather than
    reporting no firmware.

    robots.txt on waldorfmusic.com disallows only Yandex.
    """

    manufacturer_name = "Waldorf"
    manufacturer_slug = "waldorf"
    manufacturer_website = "https://waldorfmusic.com"

    INDEX_URL = "https://waldorfmusic.com/produkt-faq/"

    FAQ_LINK = re.compile(r"/faq-[a-z0-9-]+/?$")
    TITLE = re.compile(r"^FAQ\s+(?P<name>.+?)(?:\s+(?:EN|DE))?\s+[–-]\s+Waldorf Music$")
    VERSION = re.compile(r"^(?:version\s+)?v?(\d+(?:\.\d+)+)$", re.I)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._catalogue: Optional[Dict[str, Tuple[str, List[ScrapedFirmware]]]] = None

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(part) for part in version.split("."))

    def _faq_pages(self, html: str) -> List[str]:
        soup = self.parse_html(html)
        return list(dict.fromkeys(
            urljoin(self.INDEX_URL, a["href"])
            for a in soup.find_all("a", href=True)
            if self.FAQ_LINK.search(a["href"])
        ))

    def _version(self, label: str) -> Optional[str]:
        match = self.VERSION.match(" ".join(label.split()))
        return match.group(1) if match else None

    def _parse_faq(self, html: str) -> Tuple[Optional[str], Optional[List[ScrapedFirmware]]]:
        """(product name, firmware) -- firmware is None when the page has no Firmware section."""
        soup = self.parse_html(html)
        heading = next((h for h in soup.find_all("h2") if h.get_text(strip=True) == "Firmware"), None)
        column = heading.find_parent("div", class_="fusion-column-wrapper") if heading else None
        if column is None:
            return None, None
        releases: Dict[str, ScrapedFirmware] = {}
        for link in column.find_all("a", href=True):
            version = self._version(link.get_text(" ", strip=True))
            if version and version not in releases:
                releases[version] = ScrapedFirmware(version=version, download_url=link["href"])
        title = soup.find("title")
        match = self.TITLE.match(" ".join(title.get_text(" ", strip=True).split())) if title else None
        return (
            match.group("name") if match else None,
            sorted(releases.values(), key=lambda fw: self._version_key(fw.version), reverse=True),
        )

    async def _load(self) -> Optional[Dict[str, Tuple[str, List[ScrapedFirmware]]]]:
        if self._catalogue is not None:
            return self._catalogue

        index = await self.fetch_page(self.INDEX_URL)
        pages = self._faq_pages(index) if index else []
        if not pages:
            return None

        catalogue: Dict[str, Tuple[str, List[ScrapedFirmware]]] = {}
        for url in pages:
            html = await self.fetch_page(url)
            if html is None:
                return None
            name, releases = self._parse_faq(html)
            if not releases:
                continue
            if name is None:
                # A firmware download with no product to file it under.
                return None
            catalogue.setdefault(name, (url, releases))

        self._catalogue = catalogue
        return catalogue

    async def fetch_device_list(self) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(success=False, error=f"Could not read Waldorf's FAQ downloads from {self.INDEX_URL}")
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category="synthesizer",
                    firmware_page_url=url,
                    product_url=url,
                )
                for name, (url, _releases) in catalogue.items()
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(success=False, error=f"Could not read Waldorf's FAQ downloads from {self.INDEX_URL}")
        entry = catalogue.get(device_name)
        if entry is None:
            return ScraperResult(success=False, error=f"{device_name} has no firmware version on its Waldorf FAQ page")
        return ScraperResult(success=True, firmware_versions=entry[1])
