import logging
import re
from typing import Dict, Optional, Tuple
from urllib.parse import urljoin

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class KlanghelmScraper(BaseScraper):
    """Klanghelm -- DC1A, DC8C, IVGI, MJUC, SDRR, TENS, VUMT and the jr. editions.

    The four free plug-ins state their version on their own page, next to the
    installers, and that is the whole of what is published:

        Download DC1A: (version 3.5.0)  Windows: DC1A3 - Windows Installer

    Only that parenthesised statement is read. The page is full of other numbers
    that are not the release: "DC1A3" names the third generation, and its installer
    and manual carry it; "macOS 10.13" is a requirement.

    The five paid plug-ins -- DC8C, MJUC, SDRR, TENS, VUMT -- state no version
    anywhere public. Their installers come from the customer account, and they are
    catalogued as "not published" rather than left looking unchecked.

    **Any unknown path returns the home page, with a 200.** A product that moved
    would read as a page with no version, so a product page titled "Klanghelm Home"
    fails the listing instead of being catalogued as unpublished.

    Products are the `/contents/products/<code>` links on the home page, which each
    appear twice (with and without `.html`), named from each page's title.

    Ruled out, 2026-09-13:
    - `/contents/common/news.html` announces paid releases with dates, but is stale:
      the newest visible SDRR entry is 2.2.1 from 2019, while a commented-out draft in
      the same file announces SDRR 2.5.5 in May 2025. Its "latest" would be wrong,
      and a hidden draft is not published.
    - `/contents/products/DC1Aold` lists older DC1A downloads with no version numbers.
    - `/contents/downloads/` and other guessed paths: the home-page fallback.
    """

    manufacturer_name = "Klanghelm"
    manufacturer_slug = "klanghelm"
    manufacturer_website = "https://klanghelm.com"

    HOME_URL = "https://klanghelm.com/contents/common/main.html"
    FALLBACK_TITLE = "Klanghelm Home"

    PRODUCT_LINK = re.compile(r"(?:^|/)products/([A-Za-z0-9]+)(?:\.html)?$")
    STATED = re.compile(r"\(version\s+(\d+(?:\.\d+)+)\)", re.I)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._products: Optional[Dict[str, Tuple[str, Optional[str]]]] = None

    def _parse_product(self, html: str) -> Optional[Tuple[str, Optional[str]]]:
        """(name, stated version or None), or None for the home-page fallback."""
        soup = self.parse_html(html)
        title = " ".join(soup.title.get_text(" ").split()) if soup.title else ""
        if not title or title == self.FALLBACK_TITLE:
            return None
        stated = self.STATED.search(" ".join(soup.get_text(" ").split()))
        return title, (stated.group(1) if stated else None)

    async def _load(self) -> Optional[Dict[str, Tuple[str, Optional[str]]]]:
        if self._products is not None:
            return self._products

        home = await self.fetch_page(self.HOME_URL)
        if not home:
            return None
        codes = list(dict.fromkeys(
            m.group(1) for a in self.parse_html(home).find_all("a", href=True)
            if (m := self.PRODUCT_LINK.search(a["href"].strip()))
        ))
        if not codes:
            return None

        products: Dict[str, Tuple[str, Optional[str]]] = {}
        for code in codes:
            url = urljoin(self.HOME_URL, f"../products/{code}.html")
            html = await self.fetch_page(url)
            parsed = self._parse_product(html) if html else None
            if parsed is None:
                logger.warning("Klanghelm %s did not load, or returned the home page", url)
                return None
            name, version = parsed
            products[name] = (url, version)

        self._products = products
        return products

    async def fetch_device_list(self) -> ScraperResult:
        products = await self._load()
        if not products:
            return ScraperResult(success=False, error=f"No Klanghelm products read from {self.HOME_URL}")
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category="vst_plugin",
                    firmware_page_url=url,
                    product_url=url,
                    firmware_availability=None if version else "not_published",
                )
                for name, (url, version) in products.items()
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        products = await self._load()
        if not products:
            return ScraperResult(success=False, error=f"No Klanghelm products read from {self.HOME_URL}")
        _url, version = products.get(device_name, (None, None))
        return ScraperResult(
            success=True,
            firmware_versions=[ScrapedFirmware(version=version)] if version else [],
        )
