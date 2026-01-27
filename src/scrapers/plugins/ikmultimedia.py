import re
from datetime import datetime
from typing import Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class IKMultimediaScraper(BaseScraper):
    """Scraper for IK Multimedia virtual instruments and effects."""

    manufacturer_name = "IK Multimedia"
    manufacturer_slug = "ikmultimedia"
    manufacturer_website = "https://www.ikmultimedia.com"

    # Known IK Multimedia products with public product pages
    KNOWN_PRODUCTS = [
        ("Hammond B-3X", "vst_plugin", "https://www.ikmultimedia.com/products/hammondb3x/"),
        ("MODO BASS 2", "vst_plugin", "https://www.ikmultimedia.com/products/modobass2/"),
        ("MODO DRUM", "vst_plugin", "https://www.ikmultimedia.com/products/mododrum/"),
        ("SampleTank 4", "vst_plugin", "https://www.ikmultimedia.com/products/sampletank4/"),
        ("AmpliTube 5", "vst_plugin", "https://www.ikmultimedia.com/products/amplitube5/"),
        ("T-RackS 5", "vst_plugin", "https://www.ikmultimedia.com/products/trs5/"),
        ("Syntronik 2", "vst_plugin", "https://www.ikmultimedia.com/products/syntronik2/"),
        ("Miroslav Philharmonik 2", "vst_plugin", "https://www.ikmultimedia.com/products/philharmonik2/"),
    ]

    async def fetch_device_list(self) -> ScraperResult:
        """Return the list of known IK Multimedia products."""
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
        """Fetch versions from an IK Multimedia product page."""
        html = await self.fetch_page(firmware_page_url)
        if not html:
            return ScraperResult(
                success=False, error=f"Failed to fetch {firmware_page_url}"
            )

        soup = self.parse_html(html)
        firmware_versions = []
        all_text = soup.get_text()

        # IK Multimedia versions look like "Version 1.3.5" or "v1.3.5"
        version_pattern = r"[Vv](?:ersion)?\s*\.?\s*(\d+\.\d+(?:\.\d+)?)"

        # Look for version info in specs, details sections
        sections = soup.find_all(
            ["div", "section", "p", "span", "td", "li"],
            class_=re.compile(r"version|spec|info|detail|requirement|system", re.I)
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
                    download_url = f"https://www.ikmultimedia.com{download_url}"

                firmware_versions.append(
                    ScrapedFirmware(
                        version=version,
                        download_url=download_url,
                    )
                )

        # Look for version in page title or headers
        titles = soup.find_all(["h1", "h2", "h3", "title"])
        for title in titles:
            text = title.get_text()
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
