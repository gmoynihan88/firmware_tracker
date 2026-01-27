import re
from datetime import datetime
from typing import Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class TascamScraper(BaseScraper):
    """Scraper for Tascam audio equipment."""

    manufacturer_name = "Tascam"
    manufacturer_slug = "tascam"
    manufacturer_website = "https://tascam.com"

    # Known Tascam products with firmware
    KNOWN_PRODUCTS = [
        ("Model 12", "audio_interface", "https://tascam.com/us/product/model_12/support"),
        ("Model 16", "audio_interface", "https://tascam.com/us/product/model_16/support"),
        ("Model 24", "audio_interface", "https://tascam.com/us/product/model_24/support"),
        ("Portacapture X6", "audio_interface", "https://tascam.com/us/product/portacapture_x6/support"),
        ("Portacapture X8", "audio_interface", "https://tascam.com/us/product/portacapture_x8/support"),
        ("DR-40X", "audio_interface", "https://tascam.com/us/product/dr-40x/support"),
        ("DR-07X", "audio_interface", "https://tascam.com/us/product/dr-07x/support"),
        ("US-2x2HR", "audio_interface", "https://tascam.com/us/product/us-2x2hr/support"),
        ("US-4x4HR", "audio_interface", "https://tascam.com/us/product/us-4x4hr/support"),
    ]

    async def fetch_device_list(self) -> ScraperResult:
        """Return the list of known Tascam products."""
        devices = [
            ScrapedDevice(
                name=name,
                category=category,
                firmware_page_url=support_url,
                product_url=support_url.replace("/support", ""),
            )
            for name, category, support_url in self.KNOWN_PRODUCTS
        ]
        return ScraperResult(success=True, devices=devices)

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        """Fetch firmware versions from a Tascam support page."""
        html = await self.fetch_page(firmware_page_url)
        if not html:
            return ScraperResult(
                success=False, error=f"Failed to fetch {firmware_page_url}"
            )

        soup = self.parse_html(html)
        firmware_versions = []

        # Look for version patterns like "V1.50" or "Ver.1.50" or "v1.50"
        version_pattern = r"[Vv](?:er\.?)?\s*(\d+\.\d+(?:\.\d+)?)"

        # Look for date patterns near versions
        date_pattern = r"(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\w+\s+\d{1,2},?\s+\d{4}|\d{4}[-/]\d{2}[-/]\d{2})"

        # Keywords that indicate this is NOT firmware (apps, drivers, etc.)
        exclude_keywords = [
            "settings panel", "control panel", "driver", "editor",
            "remote", "controller", "manager", "utility", "app",
            "for windows", "for mac", "for ios", "for android"
        ]

        # Keywords that indicate this IS firmware
        firmware_keywords = ["firmware"]

        # Look for download items/sections
        # Include table rows (tr) without class filter since Tascam uses various classes
        download_sections = soup.find_all(
            ["div", "section", "article", "li"],
            class_=re.compile(r"download|item|row", re.I)
        )
        # Also search all table rows
        download_sections.extend(soup.find_all("tr"))

        for section in download_sections:
            text = section.get_text()
            text_lower = text.lower()

            # Skip if this looks like an app/software, not firmware
            if any(kw in text_lower for kw in exclude_keywords):
                continue

            # Only include if it explicitly mentions "firmware"
            if not any(kw in text_lower for kw in firmware_keywords):
                continue

            version_match = re.search(version_pattern, text)
            if version_match:
                version = version_match.group(1)

                # Find download link
                download_link = section.find("a", href=re.compile(r"\.(zip|exe|dmg|bin)", re.I))
                download_url = download_link["href"] if download_link else None
                if download_url and not download_url.startswith("http"):
                    download_url = f"https://tascam.com{download_url}"

                # Find date
                date_match = re.search(date_pattern, text)
                release_date = None
                if date_match:
                    date_str = date_match.group(1)
                    for fmt in ["%m-%d-%Y", "%m/%d/%Y", "%Y-%m-%d", "%B %d, %Y", "%B %d %Y"]:
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
                        changelog=text.strip()[:500] if text else None,
                    )
                )

        # Deduplicate by version
        seen = set()
        unique = []
        for fw in firmware_versions:
            if fw.version not in seen:
                seen.add(fw.version)
                unique.append(fw)

        return ScraperResult(success=True, firmware_versions=unique)
