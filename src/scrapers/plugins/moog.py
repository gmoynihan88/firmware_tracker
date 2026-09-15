import re
from datetime import datetime
from typing import Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class MoogScraper(BaseScraper):
    """Scraper for Moog Music software instruments and effects."""

    manufacturer_name = "Moog"
    manufacturer_slug = "moog"
    manufacturer_website = "https://www.moogmusic.com"

    # Moog publishes a software update page per product it sells in its store. Any
    # other slug returns the same sixteen-line shell -- verified with deliberately
    # impossible slugs, so the endpoint answers identically for anything rather than
    # 404ing on an unknown product. That is why the slugs come from the store rather
    # than being guessed. The old www.moogmusic.com/products/<slug> URLs all 404, so
    # the main site is no longer a usable source at all.
    SOFTWARE_UPDATE_URL = "https://software.moogmusic.com/softwareUpdate/{slug}"
    STORE_PRODUCT_URL = "https://software.moogmusic.com/store/{slug}"

    # The store's category pages. The products are whatever they list -- Mariana under
    # Synthesizers, the eight Moogerfooger plug-ins under Effects on 2026-09-15 -- and
    # each one's update page is at the same slug as its store page. The plug-ins were
    # missing until then: the list was kept by hand and held Mariana alone of what the
    # store sells.
    #
    # The eight plug-ins share their version history -- 1.3.0 on all eight, with the
    # same change log -- because Moog updates the Moogerfooger line as one release.
    # audit_scrapers.py reports it as one version across most of the catalogue; it
    # was checked against each plug-in's own update page on 2026-09-15.
    CATEGORY_PAGES = [
        "https://software.moogmusic.com/synthesizers",
        "https://software.moogmusic.com/store",
    ]

    # A product's store link. Bundles are skipped: "Complete Moogerfooger Effects
    # Bundle" is eight plug-ins sold together, each already listed with its own
    # version. Packages live one level deeper (/store/package/...) and do not match.
    STORE_LINK = re.compile(r"/store/(?P<slug>[a-z0-9-]+)/?$")

    # iOS apps distributed through the App Store, catalogued before the list came from
    # the store, which does not sell them. Their moogmusic.com product pages return
    # "404 Not Found | Moog Music" and their software update pages carry no version,
    # so Moog publishes nothing to read. Reported as having no firmware rather than
    # as a failure: the absence is a fact about where they are shipped.
    NO_PUBLISHED_VERSION = {"Animoog Z", "Moog Model 15", "Minimoog Model D App"}

    def _parse_category(self, html: str) -> dict:
        """Product name -> slug, for the products one category page lists."""
        products = {}
        for card in self.parse_html(html).select("div.catalogProduct"):
            title = card.select_one("p.storeProductList")
            link = next(
                (a for a in card.find_all("a", href=True) if self.STORE_LINK.search(a["href"])),
                None,
            )
            if not title or not link:
                continue
            slug = self.STORE_LINK.search(link["href"]).group("slug")
            if "bundle" in slug:
                continue
            products.setdefault(title.get_text(" ", strip=True), slug)
        return products

    # "macOS All Formats v1.2.0" names the shipping build; the Change Log lists the
    # history as <p class="sub-header">1.2.0</p> followed by its notes.
    DOWNLOAD_VERSION = re.compile(r"(?:macOS|Windows)\s+All\s+Formats\s+v(\d+(?:\.\d+)+)")
    CHANGELOG_VERSION = re.compile(r"^\d+(?:\.\d+)+$")

    async def fetch_device_list(self) -> ScraperResult:
        """Every product the store's category pages list."""
        products = {}
        for page in self.CATEGORY_PAGES:
            html = await self.fetch_page(page)
            if not html:
                # One category missing would drop its products without a word.
                return ScraperResult(success=False, error=f"Failed to fetch {page}")
            for name, slug in self._parse_category(html).items():
                products.setdefault(name, slug)

        if not products:
            return ScraperResult(
                success=False, error="No products listed on Moog's store category pages"
            )

        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category="vst_plugin",
                    firmware_page_url=self.SOFTWARE_UPDATE_URL.format(slug=slug),
                    product_url=self.STORE_PRODUCT_URL.format(slug=slug),
                )
                for name, slug in products.items()
            ],
        )

    def _parse_software_update_page(self, html: str) -> list[ScrapedFirmware]:
        """Read the shipping version and the Change Log from a software update page."""
        soup = self.parse_html(html)
        versions: list[ScrapedFirmware] = []
        seen = set()

        # The Change Log carries the history, newest first, each version in its own
        # sub-header followed by the notes for that release.
        for header in soup.find_all("p", class_="sub-header"):
            version = header.get_text(strip=True)
            if not self.CHANGELOG_VERSION.match(version) or version in seen:
                continue

            notes = []
            for sibling in header.find_next_siblings():
                if sibling.name == "p" and "sub-header" in (sibling.get("class") or []):
                    break
                text = sibling.get_text(" ", strip=True)
                if text:
                    notes.append(text)

            seen.add(version)
            versions.append(
                ScrapedFirmware(
                    version=version,
                    changelog=" ".join(notes)[:500] or None,
                )
            )

        # The download blurb names the shipping build, which need not appear in the
        # Change Log.
        for match in self.DOWNLOAD_VERSION.finditer(html):
            if match.group(1) not in seen:
                seen.add(match.group(1))
                versions.insert(0, ScrapedFirmware(version=match.group(1)))

        return versions

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        if device_name in self.NO_PUBLISHED_VERSION:
            return ScraperResult(success=True, firmware_versions=[])

        html = await self.fetch_page(firmware_page_url)
        if not html:
            return ScraperResult(
                success=False, error=f"Failed to fetch {firmware_page_url}"
            )

        versions = self._parse_software_update_page(html)
        if not versions:
            return ScraperResult(
                success=False,
                error=(
                    f"No version found for {device_name} at {firmware_page_url}; "
                    "the page returned the generic software-store shell"
                ),
            )

        return ScraperResult(success=True, firmware_versions=versions)
