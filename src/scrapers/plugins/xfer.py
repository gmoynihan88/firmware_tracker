import logging
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class XferScraper(BaseScraper):
    """Xfer Records -- Serum 2, Cthulhu, LFO Tool and Nerve.

    Xfer publishes no changelog, no release dates and no download a visitor can
    reach: every installer link, demos included, redirects to `/users/sign_in`. The
    one place a version is public is the **address** of each demo link, which Xfer
    names after the build it uploaded:

        /product_downloads/serum-2-1-5-for-macos-80e73b6e-0018-454e-8a42-12bbdf5aaa31/demo
        /product_downloads/cthulhu-demo-1-11-windows/demo
        /product_downloads/nerve-demo-1-2-3-windows/demo

    So a version here is a label, not an artefact that was checked: the file behind
    it cannot be fetched without an account. Versions are undated.

    Reading those slugs has three traps, each with a test:

    - **The product's own number runs into the version.** `serum-2-1-5` is Serum 2
      at 2.1.5; stripping the product slug first leaves `1-5`. The version is the
      first run of two or more numeric tokens, and a product whose name ends in a
      major version ("Serum 2") only accepts versions on that major.
    - **Newer slugs end in a UUID** whose groups can be all digits (`0018`). It is
      removed before reading numbers.
    - **Windows and macOS demos differ.** Cthulhu is 1.11 on Windows and 1.1 on
      macOS; Nerve 1.2.3 against 1.1. The newest is kept, as for Valhalla, and
      compared numerically -- 1.11 is newer than 1.1.

    Products are discovered from the home page's `/products/<slug>` links and named
    from each page's title ("Serum 2: Advanced Hybrid Synthesizer"). A product page
    failing fails the listing rather than dropping that product, so a device is
    never silently missing.

    Ruled out, 2026-09-13:
    - "What's New In Serum 2" (a PDF on static.xferrecords.com): features, no versions.
    - `/products` and `/products/serum`, `/products/ott`: no page.
    - Following the demo links to a filename: every one, and a made-up slug, lands
      on the sign-in page.
    """

    manufacturer_name = "Xfer Records"
    manufacturer_slug = "xfer"
    manufacturer_website = "https://xferrecords.com"

    HOME_URL = "https://xferrecords.com/"

    PRODUCT_LINK = re.compile(r"^(?:https://xferrecords\.com)?/products/([a-z0-9-]+)/?$")
    DEMO_LINK = re.compile(r"/product_downloads/([a-z0-9-]+)/demo/?$")
    UUID = re.compile(r"-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    NAME_MAJOR = re.compile(r"\s(\d+)$")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._products: Optional[Dict[str, Tuple[str, str]]] = None

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(part) for part in version.split("."))

    def _slug_version(self, slug: str) -> Optional[str]:
        """"serum-2-1-5-for-macos-<uuid>" -> "2.1.5"; "cthulhu-demo-1-11-windows" -> "1.11"."""
        runs: List[List[str]] = [[]]
        for token in self.UUID.sub("", slug).split("-"):
            if token.isdigit():
                runs[-1].append(token)
            elif runs[-1]:
                runs.append([])
        versions = [run for run in runs if len(run) >= 2]
        return ".".join(versions[0]) if versions else None

    def _parse_product(self, html: str, page_slug: str) -> Tuple[Optional[str], Optional[str]]:
        soup = self.parse_html(html)
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        name = " ".join(title.split(":")[0].split()) or None
        major = self.NAME_MAJOR.search(name or "")

        versions = []
        for link in soup.find_all("a", href=True):
            matched = self.DEMO_LINK.search(link["href"])
            # Only this product's demos: a page could carry another product's link.
            if not matched or not matched.group(1).startswith(page_slug + "-"):
                continue
            version = self._slug_version(matched.group(1))
            if version and (not major or version.split(".")[0] == major.group(1)):
                versions.append(version)
        return name, (max(versions, key=self._version_key) if versions else None)

    async def _load(self) -> Optional[Dict[str, Tuple[str, str]]]:
        if self._products is not None:
            return self._products

        home = await self.fetch_page(self.HOME_URL)
        if not home:
            return None
        pages: Dict[str, str] = {}
        for link in self.parse_html(home).find_all("a", href=True):
            matched = self.PRODUCT_LINK.match(link["href"])
            if matched:
                pages.setdefault(matched.group(1), urljoin(self.HOME_URL, link["href"]).rstrip("/"))
        if not pages:
            return None

        products: Dict[str, Tuple[str, str]] = {}
        for slug, url in pages.items():
            html = await self.fetch_page(url)
            if not html:
                logger.warning("Xfer product page %s did not load", url)
                return None
            name, version = self._parse_product(html, slug)
            if name and version:
                products[name] = (url, version)
            else:
                logger.info("Xfer %s: no demo version readable at %s", name or slug, url)

        self._products = products
        return products

    async def fetch_device_list(self) -> ScraperResult:
        products = await self._load()
        if not products:
            return ScraperResult(success=False, error=f"No Xfer products with a version found from {self.HOME_URL}")
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(name=name, category="vst_plugin", firmware_page_url=url, product_url=url)
                for name, (url, _version) in products.items()
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        products = await self._load()
        if not products:
            return ScraperResult(success=False, error=f"No Xfer products with a version found from {self.HOME_URL}")
        if device_name not in products:
            return ScraperResult(success=True, firmware_versions=[])
        return ScraperResult(success=True, firmware_versions=[ScrapedFirmware(version=products[device_name][1])])
