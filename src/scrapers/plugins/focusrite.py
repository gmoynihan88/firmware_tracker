import re
from typing import List, Optional
from urllib.parse import urljoin

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class FocusriteScraper(BaseScraper):
    """Scraper for Focusrite audio interfaces.

    Focusrite does not publish a per-device firmware version anywhere machine
    readable. Firmware ships inside Focusrite Control 2 (and Vocaster Hub), the
    downloads pages offer only a "latest" artefact with no version attached, and the
    versioned release notes on releases.focusrite.com have no index to discover the
    current one from. Product pages are therefore scraped to confirm the device still
    exists, and report no firmware rather than a failure.

    Product URLs are discovered from the category listings rather than hardcoded.
    The previous list used title-cased paths ("Scarlett%202i2%204th%20Gen") which the
    site has since replaced with lowercase slugs, so all twelve 404'd.
    """

    manufacturer_name = "Focusrite"
    manufacturer_slug = "focusrite"
    manufacturer_website = "https://focusrite.com"

    DOWNLOADS_BASE = "https://downloads.focusrite.com"

    # Current product lines. Legacy categories (saffire, isa, red, rednet, clarett-usb,
    # scarlett 1st/2nd gen) are deliberately excluded -- they are discontinued and
    # would add ~100 devices that will never see a firmware release.
    CATEGORIES = ["scarlett-4th-gen", "scarlett-3rd-gen", "clarett", "vocaster"]

    # A rendered downloads page runs to several thousand characters; a 404 renders the
    # site chrome and a "not found" message in well under that.
    MIN_RENDERED_TEXT = 1500

    def _normalise_name(self, name: str) -> str:
        """Match the site's product names to the ones already in the database.

        The site writes "Clarett⁺" with a superscript plus (U+207A) and is
        inconsistent about capitalising "gen". Without normalising, a scrape creates
        duplicate device rows and orphans the existing ones.
        """
        name = name.replace("⁺", "+")
        name = re.sub(r"\b(\d+(?:st|nd|rd|th))\s+gen\b", r"\1 Gen", name)
        return re.sub(r"\s+", " ", name).strip()

    def _category_for(self, name: str) -> str:
        lowered = name.lower()
        if "vocaster" in lowered:
            return "other"
        return "audio_interface"

    def _page_rendered(self, html: Optional[str]) -> bool:
        if not html:
            return False
        text = self.parse_html(html).get_text()
        if "not found" in text[:600].lower():
            return False
        return len(text) >= self.MIN_RENDERED_TEXT

    async def _products_in_category(self, category: str) -> List[ScrapedDevice]:
        """Read a category listing and return the products it links to."""
        url = f"{self.DOWNLOADS_BASE}/focusrite/{category}"
        html = await self.fetch_page_js(url, wait_for_timeout=20000)
        if not self._page_rendered(html):
            return []

        soup = self.parse_html(html)
        prefix = f"/focusrite/{category}/"
        seen = {}
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            # Product links sit exactly one level below the category.
            if not href.startswith(prefix) or href.count("/") != 3:
                continue
            name = self._normalise_name(anchor.get_text(strip=True))
            if name and href not in seen:
                seen[href] = name

        return [
            ScrapedDevice(
                name=name,
                category=self._category_for(name),
                firmware_page_url=urljoin(self.DOWNLOADS_BASE, href),
                product_url=urljoin(self.DOWNLOADS_BASE, href),
            )
            for href, name in seen.items()
        ]

    async def fetch_device_list(self) -> ScraperResult:
        devices = []
        for category in self.CATEGORIES:
            devices.extend(await self._products_in_category(category))

        if not devices:
            return ScraperResult(
                success=False,
                error="No products found in any Focusrite download category",
            )

        # Names are unique across categories, but guard anyway.
        unique = {device.name: device for device in devices}
        return ScraperResult(success=True, devices=list(unique.values()))

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        """Report that Focusrite publishes no per-device firmware version.

        The product page is deliberately not fetched. It carries no version to read,
        and its URL was taken from the category listing during this same scrape, so
        the product is already known to exist. Fetching all 28 pages to learn nothing
        cost ~95s of the 120s per-manufacturer budget and made the last devices fail
        on navigation timeouts under load.
        """
        return ScraperResult(success=True, firmware_versions=[])
