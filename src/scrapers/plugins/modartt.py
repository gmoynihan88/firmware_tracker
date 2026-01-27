import re
from datetime import datetime
from typing import Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class ModarttScraper(BaseScraper):
    """Scraper for Modartt virtual instruments (Pianoteq)."""

    manufacturer_name = "Modartt"
    manufacturer_slug = "modartt"
    manufacturer_website = "https://www.modartt.com"

    # Known Modartt products
    KNOWN_PRODUCTS = [
        ("Pianoteq 8", "vst_plugin", "https://www.modartt.com/pianoteq_overview"),
        ("Pianoteq 8 Stage", "vst_plugin", "https://www.modartt.com/pianoteq_overview"),
        ("Pianoteq 8 Standard", "vst_plugin", "https://www.modartt.com/pianoteq_overview"),
        ("Pianoteq 8 Pro", "vst_plugin", "https://www.modartt.com/pianoteq_overview"),
    ]

    # Public page for version history
    VERSION_HISTORY_URL = "https://www.modartt.com/pianoteq_overview"
    DOWNLOAD_PAGE_URL = "https://www.modartt.com/download"

    async def fetch_device_list(self) -> ScraperResult:
        """Return the list of known Modartt products."""
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
        """Fetch Pianoteq versions from the download/overview page."""
        # Try the download page first as it typically has version info
        html = await self.fetch_page(self.DOWNLOAD_PAGE_URL)
        if not html:
            html = await self.fetch_page(firmware_page_url)
        if not html:
            return ScraperResult(
                success=False, error=f"Failed to fetch version info"
            )

        soup = self.parse_html(html)
        firmware_versions = []
        all_text = soup.get_text()

        # Pianoteq versions look like "8.2.1" or "Pianoteq 8.2.1"
        version_pattern = r"(?:Pianoteq\s+)?(\d+\.\d+(?:\.\d+)?)"

        # Look for download sections or version info
        sections = soup.find_all(
            ["div", "section", "p", "td"],
            class_=re.compile(r"download|version|release|update", re.I)
        )

        for section in sections:
            text = section.get_text()
            version_match = re.search(version_pattern, text)

            if version_match:
                version = version_match.group(1)

                # Find download link
                download_link = section.find("a", href=re.compile(r"\.(dmg|pkg|exe|zip)", re.I))
                download_url = download_link["href"] if download_link else None
                if download_url and not download_url.startswith("http"):
                    download_url = f"https://www.modartt.com{download_url}"

                # Look for date
                date_pattern = r"(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\w+\s+\d{1,2},?\s+\d{4})"
                date_match = re.search(date_pattern, text)
                release_date = None
                if date_match:
                    date_str = date_match.group(1)
                    for fmt in ["%m/%d/%Y", "%d/%m/%Y", "%B %d, %Y", "%B %d %Y"]:
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

        # Fallback: extract any version numbers from page
        if not firmware_versions:
            # Look specifically for "Pianoteq X.X.X" patterns
            matches = re.findall(r"Pianoteq\s+(\d+\.\d+(?:\.\d+)?)", all_text)
            seen = set()
            for version in matches:
                if version not in seen:
                    seen.add(version)
                    firmware_versions.append(ScrapedFirmware(version=version))

        # Deduplicate
        seen = set()
        unique = []
        for fw in firmware_versions:
            if fw.version not in seen:
                seen.add(fw.version)
                unique.append(fw)

        return ScraperResult(success=True, firmware_versions=unique)
