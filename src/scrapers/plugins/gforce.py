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

    **The page is all there is, and it holds 48 entries.** On 2026-09-14 it showed
    releases from 06/30/2026 back to 01/25/2022; `/page/2/` and `/page/99/` return
    the same 48, and there is no JSON behind it. A product whose every release falls
    off the end would stop being listed, though its rows and stored history stay.

    **Not every release is on it.** M-Tron Pro IV 1.0.2 is installed on the
    development machine -- plug-in bundles modified 2023-11-20 -- but the page lists
    only 1.0 and 1.0.1, the product page states no version, and the app carries no
    update-check address. The scraper reports 1.0.1 because that is what GForce
    publishes; the installed version is not a source. The plug-in scanner shows the
    installed copy as newer than the tracker instead of as needing an update.

    M-Tron Pro, the product IV replaced, used to be listed with no releases so its row
    would not look broken. Its product page now redirects to M-Tron Pro IV, so it is
    no longer listed at all.
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
        """Discover products from the releases page."""
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
