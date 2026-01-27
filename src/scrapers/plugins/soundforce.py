import re
from datetime import datetime
from typing import Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class SoundForceScraper(BaseScraper):
    """Scraper for Sound-Force MIDI controllers."""

    manufacturer_name = "Sound-Force"
    manufacturer_slug = "soundforce"
    manufacturer_website = "https://sound-force.nl"

    # Known Sound-Force products
    KNOWN_PRODUCTS = [
        ("SFC-60", "midi_controller", "https://sound-force.nl/?page_id=5155"),
        ("SFC-5", "midi_controller", "https://sound-force.nl/?page_id=4617"),
        ("SFC-Mini", "midi_controller", "https://sound-force.nl/?page_id=5050"),
    ]

    async def fetch_device_list(self) -> ScraperResult:
        """Return the list of known Sound-Force products."""
        devices = [
            ScrapedDevice(
                name=name,
                category=category,
                firmware_page_url=support_url,
                product_url=support_url,
            )
            for name, category, support_url in self.KNOWN_PRODUCTS
        ]
        return ScraperResult(success=True, devices=devices)

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        """Fetch firmware versions from a Sound-Force page."""
        html = await self.fetch_page(firmware_page_url)
        if not html:
            return ScraperResult(
                success=False, error=f"Failed to fetch {firmware_page_url}"
            )

        soup = self.parse_html(html)
        firmware_versions = []

        all_text = soup.get_text()

        # Sound-Force uses patterns like "v1.11" and dates like "07/10/2024"
        version_pattern = r"[Vv](\d+\.\d+(?:\.\d+)?)"

        # Look for content sections
        content_sections = soup.find_all(
            ["div", "section", "article", "p"],
            class_=re.compile(r"content|entry|post|download|firmware", re.I)
        )

        # Also look for download links
        download_links = soup.find_all("a", href=re.compile(r"\.(zip|hex|bin|syx)", re.I))

        for section in content_sections:
            text = section.get_text()
            version_match = re.search(version_pattern, text)

            if version_match:
                version = version_match.group(1)

                # Find download link in this section
                download_link = section.find("a", href=re.compile(r"\.(zip|hex|bin|syx)", re.I))
                download_url = download_link["href"] if download_link else None
                if download_url and not download_url.startswith("http"):
                    download_url = f"https://sound-force.nl{download_url}"

                # Look for date patterns: MM/DD/YYYY or DD/MM/YYYY or YYYY-MM-DD
                date_patterns = [
                    (r"(\d{2})/(\d{2})/(\d{4})", "%m/%d/%Y"),  # MM/DD/YYYY
                    (r"(\d{4})-(\d{2})-(\d{2})", "%Y-%m-%d"),  # YYYY-MM-DD
                    (r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})", None),
                ]

                release_date = None
                for pattern, fmt in date_patterns:
                    date_match = re.search(pattern, text, re.I)
                    if date_match:
                        if fmt:
                            try:
                                date_str = date_match.group(0)
                                release_date = datetime.strptime(date_str, fmt)
                                break
                            except ValueError:
                                continue
                        else:
                            # Handle "1 Jan 2024" style
                            try:
                                day = int(date_match.group(1))
                                month_str = date_match.group(2)
                                year = int(date_match.group(3))
                                months = {
                                    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
                                    "may": 5, "jun": 6, "jul": 7, "aug": 8,
                                    "sep": 9, "oct": 10, "nov": 11, "dec": 12
                                }
                                month = months.get(month_str.lower()[:3], 1)
                                release_date = datetime(year, month, day)
                                break
                            except (ValueError, KeyError):
                                continue

                firmware_versions.append(
                    ScrapedFirmware(
                        version=version,
                        release_date=release_date,
                        download_url=download_url,
                        changelog=text.strip()[:500] if text else None,
                    )
                )

        # Check download links directly if no sections found
        if not firmware_versions:
            for link in download_links:
                href = link.get("href", "")
                link_text = link.get_text() + " " + (link.get("title", "") or "")
                parent_text = link.parent.get_text() if link.parent else ""
                combined_text = link_text + " " + parent_text

                version_match = re.search(version_pattern, combined_text)
                if version_match:
                    version = version_match.group(1)
                    download_url = href
                    if not download_url.startswith("http"):
                        download_url = f"https://sound-force.nl{download_url}"

                    firmware_versions.append(
                        ScrapedFirmware(
                            version=version,
                            download_url=download_url,
                        )
                    )

        # Final fallback: scan entire page for versions
        if not firmware_versions:
            version_matches = re.findall(version_pattern, all_text)
            seen = set()
            for version in version_matches:
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
