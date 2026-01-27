import re
from datetime import datetime
from typing import Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class FocusriteScraper(BaseScraper):
    """Scraper for Focusrite audio interfaces."""

    manufacturer_name = "Focusrite"
    manufacturer_slug = "focusrite"
    manufacturer_website = "https://focusrite.com"

    DOWNLOADS_URL = "https://downloads.focusrite.com/focusrite/"

    # Known Focusrite products
    KNOWN_PRODUCTS = [
        ("Scarlett 2i2 4th Gen", "audio_interface", "https://downloads.focusrite.com/focusrite/scarlett-4th-gen/Scarlett%202i2%204th%20Gen"),
        ("Scarlett 4i4 4th Gen", "audio_interface", "https://downloads.focusrite.com/focusrite/scarlett-4th-gen/Scarlett%204i4%204th%20Gen"),
        ("Scarlett Solo 4th Gen", "audio_interface", "https://downloads.focusrite.com/focusrite/scarlett-4th-gen/Scarlett%20Solo%204th%20Gen"),
        ("Scarlett 2i2 3rd Gen", "audio_interface", "https://downloads.focusrite.com/focusrite/scarlett-3rd-gen/Scarlett%202i2%203rd%20Gen"),
        ("Scarlett 4i4 3rd Gen", "audio_interface", "https://downloads.focusrite.com/focusrite/scarlett-3rd-gen/Scarlett%204i4%203rd%20Gen"),
        ("Scarlett 18i8 3rd Gen", "audio_interface", "https://downloads.focusrite.com/focusrite/scarlett-3rd-gen/Scarlett%2018i8%203rd%20Gen"),
        ("Scarlett 18i20 3rd Gen", "audio_interface", "https://downloads.focusrite.com/focusrite/scarlett-3rd-gen/Scarlett%2018i20%203rd%20Gen"),
        ("Clarett+ 2Pre", "audio_interface", "https://downloads.focusrite.com/focusrite/clarett-plus/Clarett+%202Pre"),
        ("Clarett+ 4Pre", "audio_interface", "https://downloads.focusrite.com/focusrite/clarett-plus/Clarett+%204Pre"),
        ("Clarett+ 8Pre", "audio_interface", "https://downloads.focusrite.com/focusrite/clarett-plus/Clarett+%208Pre"),
        ("Vocaster One", "audio_interface", "https://downloads.focusrite.com/focusrite/vocaster/Vocaster%20One"),
        ("Vocaster Two", "audio_interface", "https://downloads.focusrite.com/focusrite/vocaster/Vocaster%20Two"),
    ]

    async def fetch_device_list(self) -> ScraperResult:
        """Return the list of known Focusrite products."""
        devices = [
            ScrapedDevice(
                name=name,
                category=category,
                firmware_page_url=downloads_url,
                product_url=f"https://focusrite.com/products/{name.lower().replace(' ', '-')}",
            )
            for name, category, downloads_url in self.KNOWN_PRODUCTS
        ]
        return ScraperResult(success=True, devices=devices)

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        """Fetch firmware/driver versions from Focusrite downloads page."""
        html = await self.fetch_page(firmware_page_url)
        if not html:
            return ScraperResult(
                success=False, error=f"Failed to fetch {firmware_page_url}"
            )

        soup = self.parse_html(html)
        firmware_versions = []

        # Look for firmware/driver download sections
        download_items = soup.find_all(["div", "li", "article"], class_=re.compile(r"download|driver|firmware", re.I))

        for item in download_items:
            text = item.get_text()

            # Look for version patterns
            version_match = re.search(r"v?(\d+\.\d+(?:\.\d+)?(?:\.\d+)?)", text, re.I)
            if version_match:
                version = version_match.group(1)

                # Filter for firmware-related items (skip driver-only downloads)
                if any(kw in text.lower() for kw in ["firmware", "update", "control"]):
                    # Find download link
                    download_link = item.find("a", href=re.compile(r"\.(exe|dmg|zip|pkg)", re.I))
                    download_url = download_link["href"] if download_link else None

                    # Try to find release date
                    date_match = re.search(
                        r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\w+\s+\d{1,2},?\s+\d{4})", text
                    )
                    release_date = None
                    if date_match:
                        date_str = date_match.group(1)
                        for fmt in ["%m/%d/%Y", "%d/%m/%Y", "%B %d %Y", "%B %d, %Y"]:
                            try:
                                release_date = datetime.strptime(date_str.replace(",", ""), fmt)
                                break
                            except ValueError:
                                continue

                    # Extract notes/changelog
                    notes_elem = item.find(["p", "div"], class_=re.compile(r"notes|description", re.I))
                    changelog = notes_elem.get_text(strip=True) if notes_elem else None

                    firmware_versions.append(
                        ScrapedFirmware(
                            version=version,
                            release_date=release_date,
                            download_url=download_url,
                            changelog=changelog,
                        )
                    )

        # Deduplicate by version
        seen_versions = set()
        unique_firmware = []
        for fw in firmware_versions:
            if fw.version not in seen_versions:
                seen_versions.add(fw.version)
                unique_firmware.append(fw)

        return ScraperResult(success=True, firmware_versions=unique_firmware)
