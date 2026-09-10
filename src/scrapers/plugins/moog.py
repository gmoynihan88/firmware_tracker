import re
from datetime import datetime
from typing import Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class MoogScraper(BaseScraper):
    """Scraper for Moog Music software synthesizers."""

    manufacturer_name = "Moog"
    manufacturer_slug = "moog"
    manufacturer_website = "https://www.moogmusic.com"

    # Moog publishes a software update page per product, but only Mariana actually
    # has one: every other slug -- including invented ones -- returns the same
    # sixteen-line shell. The old www.moogmusic.com/products/<slug> URLs all 404,
    # Mariana's included, so the site is no longer a usable source at all.
    SOFTWARE_UPDATE_URL = "https://software.moogmusic.com/softwareUpdate/{slug}"
    SOFTWARE_STORE = "https://software.moogmusic.com/"

    # (name, category, slug)
    KNOWN_PRODUCTS = [
        ("Mariana", "vst_plugin", "mariana"),
        ("Animoog Z", "vst_plugin", "animoog-z"),
        ("Moog Model 15", "vst_plugin", "model-15"),
        ("Minimoog Model D App", "vst_plugin", "minimoog-model-d"),
    ]

    # iOS apps distributed through the App Store. Their moogmusic.com product pages
    # return "404 Not Found | Moog Music" and their software update pages carry no
    # version, so Moog publishes nothing to read. Reported as having no firmware
    # rather than as a failure: the absence is a fact about where they are shipped.
    NO_PUBLISHED_VERSION = {"Animoog Z", "Moog Model 15", "Minimoog Model D App"}

    # "macOS All Formats v1.2.0" names the shipping build; the Change Log lists the
    # history as <p class="sub-header">1.2.0</p> followed by its notes.
    DOWNLOAD_VERSION = re.compile(r"(?:macOS|Windows)\s+All\s+Formats\s+v(\d+(?:\.\d+)+)")
    CHANGELOG_VERSION = re.compile(r"^\d+(?:\.\d+)+$")

    async def fetch_device_list(self) -> ScraperResult:
        """Return the list of known Moog software products."""
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category=category,
                    firmware_page_url=self.SOFTWARE_UPDATE_URL.format(slug=slug),
                    product_url=self.SOFTWARE_STORE,
                )
                for name, category, slug in self.KNOWN_PRODUCTS
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
