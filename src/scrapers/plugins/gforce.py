import re
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class GForceScraper(BaseScraper):
    """Scraper for GForce Software instruments.

    Product pages carry no version -- only prices, sample-library sizes and an OS
    requirement, all of which look like versions to a loose pattern. Every release is
    instead listed on one Updates And Releases page, which also gives each product's
    canonical URL. That page is fetched once per scrape and reused.

    The previous /products/<slug>/ URLs were wrong in two ways: the path is singular
    (/product/), and several slugs have changed.
    """

    manufacturer_name = "GForce Software"
    manufacturer_slug = "gforce"
    manufacturer_website = "https://www.gforcesoftware.com"

    RELEASES_URL = "https://www.gforcesoftware.com/help/updates-and-releases/"

    # Each entry is a div.update-release-item holding a date, the product name, a
    # <h3>vX.Y.Z</h3>, the notes, and a link to the product.
    VERSION_HEADING = re.compile(r"^v(\d+(?:\.\d+)+)$")
    RELEASE_DATE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")

    # Products renamed since they were first tracked. Without these the scrape
    # creates a new row under the new name and orphans the old one.
    RENAMED = {
        "Virtual String Machine": "VSM IV",
    }

    # Listed on the site but with no releases of their own: superseded by a later
    # product that is tracked. Reported as having no firmware rather than as a
    # failure, since the absence is a fact about the product.
    SUPERSEDED = {"M-Tron Pro"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._releases: Optional[Dict[str, List[ScrapedFirmware]]] = None

    @staticmethod
    def _normalise(name: str) -> str:
        """GForce writes trademark symbols into product names ("Oberheim OB-E®")."""
        return re.sub(r"\s+", " ", name.replace("®", "").replace("™", "")).strip()

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(p) for p in re.findall(r"\d+", version)) or (0,)

    def _parse_releases(self, html: str) -> Dict[str, List[ScrapedFirmware]]:
        """Build a product -> releases map from the Updates And Releases page."""
        releases: Dict[str, List[ScrapedFirmware]] = {}

        for row in self.parse_html(html).find_all("div", class_="update-release-item"):
            description = row.find("div", class_="description")
            if not description:
                continue

            heading = description.find("h3")
            if not heading:
                continue
            version_match = self.VERSION_HEADING.match(heading.get_text(strip=True))
            if not version_match:
                continue

            release_date = None
            for text in row.stripped_strings:
                date_match = self.RELEASE_DATE.match(text)
                if date_match:
                    month, day, year = date_match.groups()
                    try:
                        release_date = datetime(int(year), int(month), int(day))
                    except ValueError:
                        release_date = None
                    break

            link = description.find("a", class_="product-link")
            if not link:
                continue
            product = self._normalise(link.get_text(strip=True).replace("View", ""))
            if not product:
                continue

            notes = description.find("ul")
            changelog = notes.get_text(" ", strip=True)[:500] if notes else None

            releases.setdefault(product, []).append(
                ScrapedFirmware(
                    version=version_match.group(1),
                    release_date=release_date,
                    download_url=urljoin(self.manufacturer_website, link.get("href") or ""),
                    changelog=changelog,
                )
            )

        return {
            product: sorted(items, key=lambda fw: self._version_key(fw.version), reverse=True)
            for product, items in releases.items()
        }

    async def _get_releases(self) -> Optional[Dict[str, List[ScrapedFirmware]]]:
        if self._releases is not None:
            return self._releases

        html = await self.fetch_page_js(self.RELEASES_URL, wait_for_timeout=25000)
        if not html:
            return None

        parsed = self._parse_releases(html)
        if not parsed:
            return None

        self._releases = parsed
        return self._releases

    async def fetch_device_list(self) -> ScraperResult:
        """Discover products from the releases page, keeping superseded ones listed."""
        releases = await self._get_releases()
        if releases is None:
            return ScraperResult(
                success=False,
                error=f"Could not read the GForce releases page at {self.RELEASES_URL}",
            )

        devices = [
            ScrapedDevice(
                name=product,
                category="vst_plugin",
                firmware_page_url=self.RELEASES_URL,
                product_url=items[0].download_url or self.manufacturer_website,
            )
            for product, items in releases.items()
        ]

        # Keep products that have no releases of their own, so their existing rows do
        # not become orphans failing every scrape.
        for name in sorted(self.SUPERSEDED):
            devices.append(
                ScrapedDevice(
                    name=name,
                    category="vst_plugin",
                    firmware_page_url=self.RELEASES_URL,
                    product_url=self.manufacturer_website,
                )
            )

        return ScraperResult(success=True, devices=devices)

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        releases = await self._get_releases()
        if releases is None:
            return ScraperResult(
                success=False,
                error=f"Could not read the GForce releases page at {self.RELEASES_URL}",
            )

        if device_name in self.SUPERSEDED:
            # Superseded by a later product; GForce lists no releases for it.
            return ScraperResult(success=True, firmware_versions=[])

        lookup = self.RENAMED.get(device_name, device_name)
        found = releases.get(lookup)
        if not found:
            return ScraperResult(
                success=False,
                error=(
                    f"{device_name} has no releases on the GForce updates page "
                    f"(looked for {lookup!r})"
                ),
            )

        return ScraperResult(success=True, firmware_versions=found)
