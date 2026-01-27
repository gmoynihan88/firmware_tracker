import re
from datetime import datetime
from typing import Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class StrymonScraper(BaseScraper):
    """Scraper for Strymon guitar pedals and effects."""

    manufacturer_name = "Strymon"
    manufacturer_slug = "strymon"
    manufacturer_website = "https://www.strymon.net"

    SUPPORT_URL = "https://www.strymon.net/support/"
    PRODUCTS_URL = "https://www.strymon.net/products/"

    # Known Strymon products with their firmware pages
    KNOWN_PRODUCTS = [
        ("BigSky", "guitar_pedal", "https://www.strymon.net/support/bigsky/"),
        ("Timeline", "guitar_pedal", "https://www.strymon.net/support/timeline/"),
        ("Mobius", "guitar_pedal", "https://www.strymon.net/support/mobius/"),
        ("Iridium", "guitar_pedal", "https://www.strymon.net/support/iridium/"),
        ("Volante", "guitar_pedal", "https://www.strymon.net/support/volante/"),
        ("NightSky", "guitar_pedal", "https://www.strymon.net/support/nightsky/"),
        ("Cloudburst", "guitar_pedal", "https://www.strymon.net/support/cloudburst/"),
        ("Zelzah", "guitar_pedal", "https://www.strymon.net/support/zelzah/"),
        ("Brig", "guitar_pedal", "https://www.strymon.net/support/brig/"),
        ("DIG", "guitar_pedal", "https://www.strymon.net/support/dig/"),
        ("El Capistan", "guitar_pedal", "https://www.strymon.net/support/elcapistan/"),
        ("Flint", "guitar_pedal", "https://www.strymon.net/support/flint/"),
        ("Deco", "guitar_pedal", "https://www.strymon.net/support/deco/"),
        ("Riverside", "guitar_pedal", "https://www.strymon.net/support/riverside/"),
        ("Sunset", "guitar_pedal", "https://www.strymon.net/support/sunset/"),
    ]

    async def fetch_device_list(self) -> ScraperResult:
        """Return the list of known Strymon products."""
        devices = [
            ScrapedDevice(
                name=name,
                category=category,
                firmware_page_url=support_url,
                product_url=f"{self.PRODUCTS_URL}{name.lower().replace(' ', '')}/",
            )
            for name, category, support_url in self.KNOWN_PRODUCTS
        ]
        return ScraperResult(success=True, devices=devices)

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        """Fetch firmware versions from a Strymon support page."""
        html = await self.fetch_page(firmware_page_url)
        if not html:
            return ScraperResult(
                success=False, error=f"Failed to fetch {firmware_page_url}"
            )

        soup = self.parse_html(html)
        firmware_versions = []

        # Look for firmware download links and version info
        # Strymon typically lists firmware in a downloads section
        download_sections = soup.find_all(["div", "section"], class_=re.compile(r"download|firmware", re.I))

        for section in download_sections:
            # Look for version numbers in text
            text = section.get_text()
            version_match = re.search(r"v?(\d+\.\d+(?:\.\d+)?)", text, re.I)
            if version_match:
                version = version_match.group(1)

                # Try to find download link
                download_link = section.find("a", href=re.compile(r"\.(zip|exe|dmg|pkg)", re.I))
                download_url = download_link["href"] if download_link else None

                # Try to find release date
                date_match = re.search(
                    r"(\w+\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})", text
                )
                release_date = None
                if date_match:
                    try:
                        release_date = datetime.strptime(
                            date_match.group(1).replace(",", ""), "%B %d %Y"
                        )
                    except ValueError:
                        pass

                # Get changelog text from the section
                changelog = text.strip()

                firmware_versions.append(
                    ScrapedFirmware(
                        version=version,
                        release_date=release_date,
                        download_url=download_url,
                        changelog=changelog,
                    )
                )

        # If no structured sections found, try to find any version info
        if not firmware_versions:
            all_text = soup.get_text()
            version_matches = re.findall(r"firmware\s+v?(\d+\.\d+(?:\.\d+)?)", all_text, re.I)
            for version in set(version_matches):
                firmware_versions.append(ScrapedFirmware(version=version))

        # Mark latest
        if firmware_versions:
            firmware_versions[0] = ScrapedFirmware(
                version=firmware_versions[0].version,
                release_date=firmware_versions[0].release_date,
                download_url=firmware_versions[0].download_url,
                changelog=firmware_versions[0].changelog,
            )

        return ScraperResult(success=True, firmware_versions=firmware_versions)
