import re
from datetime import datetime
from typing import Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class GForceScraper(BaseScraper):
    """Scraper for GForce Software virtual instruments."""

    manufacturer_name = "GForce Software"
    manufacturer_slug = "gforce"
    manufacturer_website = "https://www.gforcesoftware.com"

    # Known GForce products with public product pages
    KNOWN_PRODUCTS = [
        ("M-Tron Pro IV", "vst_plugin", "https://www.gforcesoftware.com/products/m-tron-pro-iv/"),
        ("M-Tron Pro", "vst_plugin", "https://www.gforcesoftware.com/products/m-tron-pro/"),
        ("Oberheim OB-E", "vst_plugin", "https://www.gforcesoftware.com/products/oberheim-ob-e/"),
        ("Oberheim SEM", "vst_plugin", "https://www.gforcesoftware.com/products/oberheim-sem/"),
        ("impOSCar3", "vst_plugin", "https://www.gforcesoftware.com/products/imposcar3/"),
        ("Minimonsta2", "vst_plugin", "https://www.gforcesoftware.com/products/minimonsta2/"),
        ("Virtual String Machine", "vst_plugin", "https://www.gforcesoftware.com/products/virtual-string-machine/"),
    ]

    async def fetch_device_list(self) -> ScraperResult:
        """Return the list of known GForce products."""
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
        """Fetch versions from a GForce product page."""
        html = await self.fetch_page(firmware_page_url)
        if not html:
            return ScraperResult(
                success=False, error=f"Failed to fetch {firmware_page_url}"
            )

        soup = self.parse_html(html)
        firmware_versions = []
        all_text = soup.get_text()

        # GForce versions look like "Version 1.0.2" or "v1.0.2"
        version_pattern = r"[Vv](?:ersion)?\s*(\d+\.\d+(?:\.\d+)?)"

        # Look for version/specs sections
        sections = soup.find_all(
            ["div", "section", "p", "span", "li"],
            class_=re.compile(r"version|spec|info|detail|feature", re.I)
        )

        # Also check for any element containing version text
        version_elements = soup.find_all(
            string=re.compile(r"[Vv]ersion\s*\d+\.\d+", re.I)
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
                    download_url = f"https://www.gforcesoftware.com{download_url}"

                # Look for date
                date_pattern = r"(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\w+\s+\d{1,2},?\s+\d{4}|\d{4})"
                date_match = re.search(date_pattern, text)
                release_date = None
                if date_match:
                    date_str = date_match.group(1)
                    if len(date_str) == 4:  # Just year
                        release_date = datetime(int(date_str), 1, 1)
                    else:
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
                    )
                )

        # Check version elements
        for elem in version_elements:
            if elem and elem.parent:
                text = elem.parent.get_text()
                version_match = re.search(version_pattern, text)
                if version_match:
                    version = version_match.group(1)
                    if not any(fw.version == version for fw in firmware_versions):
                        firmware_versions.append(ScrapedFirmware(version=version))

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
