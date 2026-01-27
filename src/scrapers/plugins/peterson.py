import re
from datetime import datetime
from typing import Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class PetersonScraper(BaseScraper):
    """Scraper for Peterson strobe tuners."""

    manufacturer_name = "Peterson"
    manufacturer_slug = "peterson"
    manufacturer_website = "https://www.petersontuners.com"

    # Known Peterson products with firmware
    KNOWN_PRODUCTS = [
        ("StroboStomp Mini", "guitar_pedal", "https://www.petersontuners.com/products/strobostompmini/"),
        ("StroboStomp HD", "guitar_pedal", "https://www.petersontuners.com/products/strobostomphd/"),
        ("StroboPlus HD", "guitar_pedal", "https://www.petersontuners.com/products/stroboplushd/"),
        ("StroboClip HD", "guitar_pedal", "https://www.petersontuners.com/products/strobocliphd/"),
        ("StroboRack", "guitar_pedal", "https://www.petersontuners.com/products/stroborack/"),
        ("Body Beat Sync", "guitar_pedal", "https://www.petersontuners.com/products/bodybeatsync/"),
    ]

    SUPPORT_URL = "https://www.petersontuners.com/support/downloads/"

    async def fetch_device_list(self) -> ScraperResult:
        """Return the list of known Peterson products."""
        devices = [
            ScrapedDevice(
                name=name,
                category=category,
                firmware_page_url=url,
                product_url=url,
            )
            for name, category, url in self.KNOWN_PRODUCTS
        ]
        return ScraperResult(success=True, devices=devices)

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        """Fetch firmware versions from Peterson product/support pages."""
        # Try the product page first
        html = await self.fetch_page(firmware_page_url)

        # Also try the main downloads page
        downloads_html = await self.fetch_page(self.SUPPORT_URL)

        if not html and not downloads_html:
            return ScraperResult(
                success=False, error=f"Failed to fetch firmware info"
            )

        firmware_versions = []

        for page_html in [html, downloads_html]:
            if not page_html:
                continue

            soup = self.parse_html(page_html)
            all_text = soup.get_text()

            # Peterson versions look like "v1.0.0" or "Version 1.0" or "Firmware 1.0.0"
            version_pattern = r"(?:[Vv](?:ersion)?|[Ff]irmware)\s*\.?\s*(\d+\.\d+(?:\.\d+)?)"

            # Look for download sections
            sections = soup.find_all(
                ["div", "section", "article", "li", "td", "tr"],
                class_=re.compile(r"download|firmware|update|software|support", re.I)
            )

            # Also look for links mentioning the device name
            device_name_pattern = device_name.lower().replace(" ", "").replace("-", "")
            relevant_sections = soup.find_all(
                string=re.compile(re.escape(device_name), re.I)
            )

            for section in sections:
                text = section.get_text()

                # Check if this section is relevant to our device
                if device_name.lower() not in text.lower() and device_name_pattern not in text.lower().replace(" ", "").replace("-", ""):
                    continue

                version_match = re.search(version_pattern, text)

                if version_match:
                    version = version_match.group(1)

                    # Find download link
                    download_link = section.find("a", href=re.compile(r"\.(zip|exe|dmg|bin|hex)", re.I))
                    download_url = download_link["href"] if download_link else None
                    if download_url and not download_url.startswith("http"):
                        download_url = f"https://www.petersontuners.com{download_url}"

                    # Look for date
                    date_pattern = r"(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\w+\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2})"
                    date_match = re.search(date_pattern, text)
                    release_date = None
                    if date_match:
                        date_str = date_match.group(1)
                        for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%B %d, %Y", "%B %d %Y"]:
                            try:
                                release_date = datetime.strptime(date_str.replace(",", ""), fmt)
                                break
                            except ValueError:
                                continue

                    firmware_versions.append(
                        ScrapedFirmware(
                            version=version,
                            release_date=release_date,
                            download_url=download_url,
                        )
                    )

            # Check elements that mention the device
            for elem in relevant_sections:
                if elem and elem.parent:
                    parent = elem.parent
                    # Go up a few levels to find containing section
                    for _ in range(3):
                        if parent.parent:
                            parent = parent.parent

                    text = parent.get_text()
                    version_match = re.search(version_pattern, text)
                    if version_match:
                        version = version_match.group(1)
                        if not any(fw.version == version for fw in firmware_versions):
                            firmware_versions.append(ScrapedFirmware(version=version))

        # Deduplicate
        seen = set()
        unique = []
        for fw in firmware_versions:
            if fw.version not in seen:
                seen.add(fw.version)
                unique.append(fw)

        return ScraperResult(success=True, firmware_versions=unique)
