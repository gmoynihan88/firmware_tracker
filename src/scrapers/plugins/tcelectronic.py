import re
from datetime import datetime
from typing import Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class TCElectronicScraper(BaseScraper):
    """Scraper for TC Electronic guitar pedals and effects."""

    manufacturer_name = "TC Electronic"
    manufacturer_slug = "tcelectronic"
    manufacturer_website = "https://www.tcelectronic.com"

    # Known TC Electronic products with firmware updates
    KNOWN_PRODUCTS = [
        ("Ditto+", "guitar_pedal", "https://www.tcelectronic.com/product.html?modelCode=P0DPA"),
        ("Ditto X4", "guitar_pedal", "https://www.tcelectronic.com/product.html?modelCode=P0CML"),
        ("Ditto Looper", "guitar_pedal", "https://www.tcelectronic.com/product.html?modelCode=P0CM7"),
        ("Flashback 2", "guitar_pedal", "https://www.tcelectronic.com/product.html?modelCode=P0DDD"),
        ("Hall of Fame 2", "guitar_pedal", "https://www.tcelectronic.com/product.html?modelCode=P0DDC"),
        ("Plethora X5", "guitar_pedal", "https://www.tcelectronic.com/product.html?modelCode=P0DQS"),
        ("Plethora X3", "guitar_pedal", "https://www.tcelectronic.com/product.html?modelCode=P0DWB"),
        ("PolyTune 3", "guitar_pedal", "https://www.tcelectronic.com/product.html?modelCode=P0DDG"),
    ]

    async def fetch_device_list(self) -> ScraperResult:
        """Return the list of known TC Electronic products."""
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
        """Fetch firmware versions from a TC Electronic product page."""
        html = await self.fetch_page(firmware_page_url)
        if not html:
            return ScraperResult(
                success=False, error=f"Failed to fetch {firmware_page_url}"
            )

        soup = self.parse_html(html)
        firmware_versions = []
        all_text = soup.get_text()

        # TC Electronic versions look like "v1.0.0" or "Version 1.0.0" or "Firmware 1.0"
        version_pattern = r"(?:[Vv](?:ersion)?|[Ff]irmware)\s*\.?\s*(\d+\.\d+(?:\.\d+)?)"

        # Look for download/support sections
        sections = soup.find_all(
            ["div", "section", "article", "li", "td"],
            class_=re.compile(r"download|support|firmware|software|update|version", re.I)
        )

        # Also check for download links
        download_links = soup.find_all("a", href=re.compile(r"download|firmware|update", re.I))

        for section in sections:
            text = section.get_text()
            version_match = re.search(version_pattern, text)

            if version_match:
                version = version_match.group(1)

                # Find download link
                download_link = section.find("a", href=re.compile(r"\.(zip|exe|dmg|bin)", re.I))
                download_url = download_link["href"] if download_link else None
                if download_url and not download_url.startswith("http"):
                    download_url = f"https://www.tcelectronic.com{download_url}"

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

        # Check download links directly
        for link in download_links:
            text = link.get_text() + " " + (link.get("title", "") or "")
            version_match = re.search(version_pattern, text)
            if version_match:
                version = version_match.group(1)
                if not any(fw.version == version for fw in firmware_versions):
                    download_url = link.get("href")
                    if download_url and not download_url.startswith("http"):
                        download_url = f"https://www.tcelectronic.com{download_url}"
                    firmware_versions.append(
                        ScrapedFirmware(version=version, download_url=download_url)
                    )

        # Fallback: scan entire page
        if not firmware_versions:
            matches = re.findall(version_pattern, all_text)
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
