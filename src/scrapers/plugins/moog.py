import re
from datetime import datetime
from typing import Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class MoogScraper(BaseScraper):
    """Scraper for Moog Music software synthesizers."""

    manufacturer_name = "Moog"
    manufacturer_slug = "moog"
    manufacturer_website = "https://www.moogmusic.com"

    # Known Moog software products
    KNOWN_PRODUCTS = [
        ("Mariana", "vst_plugin", "https://www.moogmusic.com/products/mariana"),
        ("Animoog Z", "vst_plugin", "https://www.moogmusic.com/products/animoog-z"),
        ("Moog Model 15", "vst_plugin", "https://www.moogmusic.com/products/model-15-app"),
        ("Minimoog Model D App", "vst_plugin", "https://www.moogmusic.com/products/minimoog-model-d-app"),
    ]

    async def fetch_device_list(self) -> ScraperResult:
        """Return the list of known Moog software products."""
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
        """Fetch versions from a Moog product page."""
        html = await self.fetch_page(firmware_page_url)
        if not html:
            return ScraperResult(
                success=False, error=f"Failed to fetch {firmware_page_url}"
            )

        soup = self.parse_html(html)
        firmware_versions = []
        all_text = soup.get_text()

        # Moog versions look like "Version 1.2.0" or "v1.2.0"
        version_pattern = r"[Vv](?:ersion)?\s*\.?\s*(\d+\.\d+(?:\.\d+)?)"

        # Look for version info sections
        sections = soup.find_all(
            ["div", "section", "p", "span", "td", "li"],
            class_=re.compile(r"version|spec|info|detail|feature|description", re.I)
        )

        for section in sections:
            text = section.get_text()
            version_match = re.search(version_pattern, text)

            if version_match:
                version = version_match.group(1)

                # Find download link (if available on public page)
                download_link = section.find("a", href=re.compile(r"\.(dmg|pkg|exe|zip)", re.I))
                download_url = download_link["href"] if download_link else None
                if download_url and not download_url.startswith("http"):
                    download_url = f"https://www.moogmusic.com{download_url}"

                # Look for release date
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
                    )
                )

        # Check meta tags and structured data
        meta_version = soup.find("meta", {"name": re.compile(r"version", re.I)})
        if meta_version and meta_version.get("content"):
            version_match = re.search(version_pattern, meta_version["content"])
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
