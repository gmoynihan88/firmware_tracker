import re
from datetime import datetime
from typing import Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class CrumarScraper(BaseScraper):
    """Scraper for Crumar keyboard instruments."""

    manufacturer_name = "Crumar"
    manufacturer_slug = "crumar"
    manufacturer_website = "https://www.crumar.it"

    # Known Crumar products
    KNOWN_PRODUCTS = [
        ("D9-X", "synthesizer", "https://www.crumar.it/d9-x/"),
        ("Seven", "synthesizer", "https://www.crumar.it/seven/"),
        ("Mojo 61", "synthesizer", "https://www.crumar.it/mojo-61/"),
        ("Mojo Desktop", "synthesizer", "https://www.crumar.it/mojo-desktop/"),
    ]

    DOWNLOADS_URL = "https://www.crumar.it/downloads/"

    async def fetch_device_list(self) -> ScraperResult:
        """Return the list of known Crumar products."""
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
        """Fetch firmware versions from Crumar pages."""
        # Try product page
        html = await self.fetch_page(firmware_page_url)

        # Also try downloads page
        downloads_html = await self.fetch_page(self.DOWNLOADS_URL)

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

            # Crumar versions look like "v1.0.0" or "Version 1.0" or "OS 1.0"
            version_pattern = r"(?:[Vv](?:ersion)?|OS)\s*\.?\s*(\d+\.\d+(?:\.\d+)?)"

            # Look for download/firmware sections
            sections = soup.find_all(
                ["div", "section", "article", "li", "td", "p"],
                class_=re.compile(r"download|firmware|update|software|version", re.I)
            )

            # Also look for links
            download_links = soup.find_all("a", href=re.compile(r"\.(zip|exe|bin|syx)", re.I))

            for section in sections:
                text = section.get_text()

                # Check if relevant to device
                device_pattern = device_name.lower().replace("-", "").replace(" ", "")
                if device_pattern not in text.lower().replace("-", "").replace(" ", ""):
                    continue

                version_match = re.search(version_pattern, text)

                if version_match:
                    version = version_match.group(1)

                    # Find download link
                    download_link = section.find("a", href=re.compile(r"\.(zip|exe|bin|syx)", re.I))
                    download_url = download_link["href"] if download_link else None
                    if download_url and not download_url.startswith("http"):
                        download_url = f"https://www.crumar.it{download_url}"

                    # Look for date
                    date_pattern = r"(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{4}-\d{2}-\d{2}|\w+\s+\d{1,2},?\s+\d{4})"
                    date_match = re.search(date_pattern, text)
                    release_date = None
                    if date_match:
                        date_str = date_match.group(1)
                        for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%B %d, %Y", "%B %d %Y"]:
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

            # Check download links
            for link in download_links:
                href = link.get("href", "")
                text = link.get_text() + " " + (link.get("title", "") or "")
                parent_text = link.parent.get_text() if link.parent else ""

                device_pattern = device_name.lower().replace("-", "").replace(" ", "")
                combined = (text + " " + parent_text + " " + href).lower().replace("-", "").replace(" ", "")

                if device_pattern in combined:
                    version_match = re.search(version_pattern, text + " " + parent_text)
                    if version_match:
                        version = version_match.group(1)
                        if not any(fw.version == version for fw in firmware_versions):
                            download_url = href
                            if not download_url.startswith("http"):
                                download_url = f"https://www.crumar.it{download_url}"
                            firmware_versions.append(
                                ScrapedFirmware(version=version, download_url=download_url)
                            )

        # Deduplicate
        seen = set()
        unique = []
        for fw in firmware_versions:
            if fw.version not in seen:
                seen.add(fw.version)
                unique.append(fw)

        return ScraperResult(success=True, firmware_versions=unique)
