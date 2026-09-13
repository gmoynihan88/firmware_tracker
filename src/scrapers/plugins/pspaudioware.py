import re
from typing import Dict, List, Optional, Tuple

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class PSPaudiowareScraper(BaseScraper):
    """PSPaudioware, whose versions are only stated in its trial installers' names.

    Fifty-seven plug-ins on `/products`, and **not one version anywhere in the
    page text**. The number is in the filename behind the "30-day trial" button:

        .../PSP_VintageWarmer2/OSX/native/PSP_VintageWarmer2_2.11.0_macOS.dmg
        .../release/PSP_Echo/OSX/PSP_Echo_1.5.3_macOS.dmg

    **PSP serves those installers from two different hosts**, and matching on the
    first one found drops a quarter of the catalogue silently:

        https://download-eu2.pspaudioware.net/...              31 products
        https://s3.us-west-1.amazonaws.com/download-us1...     12 products

    Anchoring on the host took 31 of 43; anchoring on the *filename*, whatever
    serves it, takes all 43. The product page reads identically either way --
    both say "30-day trial for macOS" -- so the shortfall is invisible without
    counting.

    **The downloads page is genuinely gated**, unlike Bitwig's. `/downloads`
    redirects to `/UserArea/demos` and its body is a login form: "You need to be
    logged into your PSP account to proceed!" with no version list anywhere on
    it. The trial links on the public product pages are the way in.

    **Fourteen products publish no installer at all** -- the bundles (MixPack2,
    StereoPack) and the older plug-ins (PianoVerb, RetroQ, ClassicQ, N2O and
    friends), which have no trial button rather than a trial button that is
    broken. They are listed with `firmware_availability="not_published"` so the
    catalogue says why instead of showing a blank that reads like a scraper that
    stopped working.

    **The version is never taken from the product's name.** PSP ships editions:
    `PSP auralComp v. 2` is the product, and its installer says 2.0.2. Reading
    the "v. 2" would record an edition as a release, and it is the only
    version-shaped string on that page that a text scan would find.

    The other trap a text scan hits here is `10.14`, which appears four times on
    a typical page as the minimum macOS. Nothing outside the download hrefs is
    read, so neither can reach the database.

    Windows and macOS are published as separate installers and have agreed on the
    version on every product checked; if they ever disagree the higher wins.

    **No dates.** PSP states none on the product pages, and the changelogs live
    inside the operation-manual PDFs, so versions are stored undated.
    """

    manufacturer_name = "PSPaudioware"
    manufacturer_slug = "pspaudioware"
    manufacturer_website = "https://www.pspaudioware.com"

    PRODUCTS_URL = "https://www.pspaudioware.com/products"

    # Any product page, from the index.
    PRODUCT_HREF = re.compile(r"^/products/psp-[a-z0-9-]+$", re.I)

    # "PSP_VintageWarmer2_2.11.0_macOS.dmg", "PSP_Echo_1.5.3_macOS.dmg" -- matched
    # on the filename rather than the host, because PSP uses two of those.
    INSTALLER = re.compile(
        r"/([A-Za-z0-9][A-Za-z0-9_\-.]*?)_v?(\d+(?:\.\d+)+)_?"
        r"(?:macOS|OSX|Win|Windows)?[A-Za-z0-9_]*\.(?:dmg|exe|pkg|zip)",
        re.I,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._catalogue: Optional[Dict[str, Tuple[str, Optional[str]]]] = None

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(part) for part in re.findall(r"\d+", version)) or (0,)

    def _parse_product(self, html: str) -> Tuple[Optional[str], Optional[str]]:
        """(display name, version) for one product page. Version may be None."""
        soup = self.parse_html(html)
        heading = soup.find("h1")
        name = " ".join(heading.get_text(" ", strip=True).split()) if heading else None
        if not name:
            return None, None

        versions = []
        for anchor in soup.find_all("a", href=True):
            matched = self.INSTALLER.search(anchor["href"])
            if matched:
                versions.append(matched.group(2))

        if not versions:
            return name, None
        return name, max(versions, key=self._version_key)

    async def _load(self) -> Optional[Dict[str, Tuple[str, Optional[str]]]]:
        """name -> (product URL, version or None), one fetch per product page."""
        if self._catalogue is not None:
            return self._catalogue

        index = await self.fetch_page(self.PRODUCTS_URL)
        if not index:
            return None

        soup = self.parse_html(index)
        paths = sorted({
            anchor["href"] for anchor in soup.find_all("a", href=True)
            if self.PRODUCT_HREF.match(anchor["href"])
        })
        if not paths:
            return None

        catalogue: Dict[str, Tuple[str, Optional[str]]] = {}
        for path in paths:
            url = self.manufacturer_website + path
            html = await self.fetch_page(url)
            if not html:
                continue
            name, version = self._parse_product(html)
            if name:
                catalogue.setdefault(name, (url, version))

        if not catalogue:
            return None
        self._catalogue = catalogue
        return catalogue

    async def fetch_device_list(self) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(
                success=False, error=f"No products found at {self.PRODUCTS_URL}"
            )

        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category="vst_plugin",
                    firmware_page_url=url,
                    product_url=url,
                    # No trial installer on the page, so PSP states no version
                    # publicly for this one. See the class docstring.
                    firmware_availability=None if version else "not_published",
                )
                for name, (url, version) in sorted(catalogue.items())
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(
                success=False, error=f"No products found at {self.PRODUCTS_URL}"
            )

        entry = catalogue.get(device_name)
        if entry is None or entry[1] is None:
            # Either dropped from the index, or one of the fourteen with no
            # installer. The index loaded, so both are absences rather than breaks.
            return ScraperResult(success=True, firmware_versions=[])

        return ScraperResult(
            success=True, firmware_versions=[ScrapedFirmware(version=entry[1])]
        )
