import re
from datetime import datetime
from typing import Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class TALScraper(BaseScraper):
    """Scraper for TAL Software (Togu Audio Line) virtual instruments."""

    manufacturer_name = "TAL Software"
    manufacturer_slug = "tal"
    manufacturer_website = "https://tal-software.com"

    # Known TAL products
    KNOWN_PRODUCTS = [
        ("TAL-U-NO-LX-V2", "vst_plugin", "https://tal-software.com/products/tal-u-no-lx"),
        ("TAL-J-8", "vst_plugin", "https://tal-software.com/products/tal-j-8"),
        ("TAL-Sampler", "vst_plugin", "https://tal-software.com/products/tal-sampler"),
        ("TAL-MOD", "vst_plugin", "https://tal-software.com/products/tal-mod"),
        ("TAL-DAC", "vst_plugin", "https://tal-software.com/products/tal-dac"),
        ("TAL-Drum", "vst_plugin", "https://tal-software.com/products/tal-drum"),
        ("TAL-BassLine-101", "vst_plugin", "https://tal-software.com/products/tal-bassline-101"),
        ("TAL-NoiseMaker", "vst_plugin", "https://tal-software.com/products/tal-noisemaker"),
        ("TAL-Reverb-4", "vst_plugin", "https://tal-software.com/products/tal-reverb-4"),
    ]

    async def fetch_device_list(self) -> ScraperResult:
        """Return the list of known TAL products."""
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
        """Fetch versions from a TAL product page."""
        html = await self.fetch_page(firmware_page_url)
        if not html:
            return ScraperResult(
                success=False, error=f"Failed to fetch {firmware_page_url}"
            )

        soup = self.parse_html(html)
        firmware_versions = []
        all_text = soup.get_text()

        # TAL versions look like "v5.1.3" or "Version 2.0.4"
        version_pattern = r"[Vv](?:ersion)?\s*(\d+\.\d+(?:\.\d+)?)"

        # TAL product pages typically have version info and changelog
        # Look for version/changelog sections
        sections = soup.find_all(
            ["div", "section", "p", "span", "td", "li", "article"],
            class_=re.compile(r"version|changelog|update|download|info|content", re.I)
        )

        # Also look for download buttons/links
        download_sections = soup.find_all(
            ["div", "a"],
            class_=re.compile(r"download|button", re.I)
        )

        for section in sections + download_sections:
            text = section.get_text()
            version_match = re.search(version_pattern, text)

            if version_match:
                version = version_match.group(1)

                # Find download link
                download_link = section.find("a", href=re.compile(r"\.(dmg|pkg|exe|zip|vst)", re.I))
                if not download_link:
                    download_link = section.find_parent("a")
                download_url = None
                if download_link and download_link.get("href"):
                    download_url = download_link["href"]
                    if not download_url.startswith("http"):
                        download_url = f"https://tal-software.com{download_url}"

                # TAL uses dates like "29.12.2025" (DD.MM.YYYY)
                date_patterns = [
                    (r"(\d{1,2})\.(\d{1,2})\.(\d{4})", "dmy"),  # DD.MM.YYYY
                    (r"(\d{1,2})/(\d{1,2})/(\d{4})", "mdy"),   # MM/DD/YYYY
                    (r"(\w+)\s+(\d{4})", "month_year"),         # Month YYYY
                ]
                release_date = None
                for pattern, fmt_type in date_patterns:
                    date_match = re.search(pattern, text)
                    if date_match:
                        try:
                            if fmt_type == "dmy":
                                day, month, year = date_match.groups()
                                release_date = datetime(int(year), int(month), int(day))
                            elif fmt_type == "mdy":
                                month, day, year = date_match.groups()
                                release_date = datetime(int(year), int(month), int(day))
                            elif fmt_type == "month_year":
                                month_str, year = date_match.groups()
                                release_date = datetime.strptime(f"{month_str} {year}", "%B %Y")
                            break
                        except ValueError:
                            continue

                # Get changelog text
                changelog = None
                changelog_section = section.find(
                    ["ul", "div", "p"],
                    class_=re.compile(r"changelog|changes|notes", re.I)
                )
                if changelog_section:
                    changelog = changelog_section.get_text(strip=True)[:500]

                firmware_versions.append(
                    ScrapedFirmware(
                        version=version,
                        release_date=release_date,
                        download_url=download_url,
                        changelog=changelog,
                    )
                )

        # Fallback: scan entire page for version strings
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
