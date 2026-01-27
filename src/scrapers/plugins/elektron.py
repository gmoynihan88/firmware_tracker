import re
from datetime import datetime
from typing import Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class ElektronScraper(BaseScraper):
    """Scraper for Elektron synthesizers and drum machines."""

    manufacturer_name = "Elektron"
    manufacturer_slug = "elektron"
    manufacturer_website = "https://www.elektron.se"

    SUPPORT_URL = "https://www.elektron.se/support/"

    # Known Elektron products
    KNOWN_PRODUCTS = [
        ("Digitakt", "synthesizer", "https://www.elektron.se/support/?connection=digitakt"),
        ("Digitakt II", "synthesizer", "https://www.elektron.se/support/?connection=digitakt-ii"),
        ("Digitone", "synthesizer", "https://www.elektron.se/support/?connection=digitone"),
        ("Digitone II", "synthesizer", "https://www.elektron.se/support/?connection=digitone-ii"),
        ("Syntakt", "synthesizer", "https://www.elektron.se/support/?connection=syntakt"),
        ("Octatrack MKII", "synthesizer", "https://www.elektron.se/support/?connection=octatrack-mkii"),
        ("Analog Four MKII", "synthesizer", "https://www.elektron.se/support/?connection=analog-four-mkii"),
        ("Analog Rytm MKII", "synthesizer", "https://www.elektron.se/support/?connection=analog-rytm-mkii"),
        ("Model:Samples", "synthesizer", "https://www.elektron.se/support/?connection=model-samples"),
        ("Model:Cycles", "synthesizer", "https://www.elektron.se/support/?connection=model-cycles"),
        ("Analog Heat MKII", "synthesizer", "https://www.elektron.se/support/?connection=analog-heat-mkii"),
    ]

    async def fetch_device_list(self) -> ScraperResult:
        """Return the list of known Elektron products."""
        devices = [
            ScrapedDevice(
                name=name,
                category=category,
                firmware_page_url=support_url,
                product_url=f"https://www.elektron.se/{name.lower().replace(' ', '-').replace(':', '')}/",
            )
            for name, category, support_url in self.KNOWN_PRODUCTS
        ]
        return ScraperResult(success=True, devices=devices)

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        """Fetch firmware versions from an Elektron support page."""
        html = await self.fetch_page(firmware_page_url)
        if not html:
            return ScraperResult(
                success=False, error=f"Failed to fetch {firmware_page_url}"
            )

        soup = self.parse_html(html)
        firmware_versions = []

        # Look for OS/firmware sections
        # Elektron typically has "OS" sections with version info
        os_sections = soup.find_all(["div", "section", "article"], class_=re.compile(r"download|os|firmware", re.I))

        for section in os_sections:
            text = section.get_text()

            # Look for OS version patterns like "OS 1.40" or "v1.40"
            version_match = re.search(r"(?:OS\s+)?v?(\d+\.\d+(?:\.\d+)?[a-zA-Z]?)", text, re.I)
            if version_match:
                version = version_match.group(1)

                # Try to find download link
                download_link = section.find("a", href=re.compile(r"\.(syx|zip|bin)", re.I))
                download_url = download_link["href"] if download_link else None
                if download_url and not download_url.startswith("http"):
                    download_url = f"https://www.elektron.se{download_url}"

                # Try to find release date
                date_match = re.search(
                    r"(\d{4}-\d{2}-\d{2}|\w+\s+\d{1,2},?\s+\d{4})", text
                )
                release_date = None
                if date_match:
                    date_str = date_match.group(1)
                    try:
                        if "-" in date_str:
                            release_date = datetime.strptime(date_str, "%Y-%m-%d")
                        else:
                            release_date = datetime.strptime(
                                date_str.replace(",", ""), "%B %d %Y"
                            )
                    except ValueError:
                        pass

                # Get changelog from section
                changelog_elem = section.find(["ul", "div"], class_=re.compile(r"changelog|changes|notes", re.I))
                changelog = changelog_elem.get_text(strip=True) if changelog_elem else None

                firmware_versions.append(
                    ScrapedFirmware(
                        version=version,
                        release_date=release_date,
                        download_url=download_url,
                        changelog=changelog,
                    )
                )

        # Fallback: look for version info in page text
        if not firmware_versions:
            all_text = soup.get_text()
            version_matches = re.findall(r"OS\s+v?(\d+\.\d+(?:\.\d+)?[a-zA-Z]?)", all_text, re.I)
            for version in set(version_matches):
                firmware_versions.append(ScrapedFirmware(version=version))

        return ScraperResult(success=True, firmware_versions=firmware_versions)
