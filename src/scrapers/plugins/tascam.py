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

        # Tascam support pages typically have download sections with firmware info
        # Look for firmware/update related sections
        download_sections = soup.find_all(
            ["div", "section", "article", "li"],
            class_=re.compile(r"download|firmware|update|software", re.I)
        )

        # Also look for links containing firmware
        firmware_links = soup.find_all("a", href=re.compile(r"firmware|update", re.I))

        all_text = soup.get_text()

        # Look for version patterns like "V1.50" or "Ver.1.50" or "v1.50"
        version_pattern = r"[Vv](?:er\.?)?\s*(\d+\.\d+(?:\.\d+)?)"
        version_matches = re.findall(version_pattern, all_text)

        # Look for date patterns near versions
        date_pattern = r"(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\w+\s+\d{1,2},?\s+\d{4}|\d{4}[-/]\d{2}[-/]\d{2})"

        for section in download_sections:
            text = section.get_text()
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

        # Fallback: extract versions from full page text
        if not firmware_versions and version_matches:
            seen = set()
            for version in version_matches:
                if version not in seen:
                    seen.add(version)
                    firmware_versions.append(ScrapedFirmware(version=version))

        return ScraperResult(success=True, firmware_versions=firmware_versions)
