import re
from datetime import datetime
from typing import Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class BossScraper(BaseScraper):
    """Scraper for Boss/Roland guitar pedals and effects."""

    manufacturer_name = "Boss"
    manufacturer_slug = "boss"
    manufacturer_website = "https://www.boss.info"

    # Known Boss products with firmware updates
    KNOWN_PRODUCTS = [
        ("IR-200", "guitar_pedal", "https://www.boss.info/us/support/by_product/ir-200/updates_drivers/"),
        ("DD-500", "guitar_pedal", "https://www.boss.info/global/support/by_product/dd-500/updates_drivers/"),
        ("RC-500", "guitar_pedal", "https://www.boss.info/us/support/by_product/rc-500/updates_drivers/"),
        ("RC-600", "guitar_pedal", "https://www.boss.info/us/support/by_product/rc-600/updates_drivers/"),
        ("MD-500", "guitar_pedal", "https://www.boss.info/us/support/by_product/md-500/updates_drivers/"),
        ("RV-500", "guitar_pedal", "https://www.boss.info/us/support/by_product/rv-500/updates_drivers/"),
        ("GT-1000", "guitar_pedal", "https://www.boss.info/us/support/by_product/gt-1000/updates_drivers/"),
        ("GT-1000CORE", "guitar_pedal", "https://www.boss.info/us/support/by_product/gt-1000core/updates_drivers/"),
        ("GX-100", "guitar_pedal", "https://www.boss.info/us/support/by_product/gx-100/updates_drivers/"),
        ("ME-90", "guitar_pedal", "https://www.boss.info/us/support/by_product/me-90/updates_drivers/"),
        ("ME-90B", "guitar_pedal", "https://www.boss.info/us/support/by_product/me-90b/updates_drivers/"),
        ("SY-300", "guitar_pedal", "https://www.boss.info/us/support/by_product/sy-300/updates_drivers/"),
        ("SY-1000", "guitar_pedal", "https://www.boss.info/us/support/by_product/sy-1000/updates_drivers/"),
        ("EV-1-WL", "guitar_pedal", "https://www.boss.info/us/support/by_product/ev-1-wl/updates_drivers/"),
        ("Katana-100 MkII", "guitar_pedal", "https://www.boss.info/us/support/by_product/katana-100_mkii/updates_drivers/"),
        ("Katana-Artist MkII", "guitar_pedal", "https://www.boss.info/us/support/by_product/katana-artist_mkii/updates_drivers/"),
    ]

    async def fetch_device_list(self) -> ScraperResult:
        """Return the list of known Boss products."""
        devices = [
            ScrapedDevice(
                name=name,
                category=category,
                firmware_page_url=support_url,
                product_url=f"https://www.boss.info/us/products/{name.lower().replace(' ', '_').replace('-', '-')}/",
            )
            for name, category, support_url in self.KNOWN_PRODUCTS
        ]
        return ScraperResult(success=True, devices=devices)

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        """Fetch firmware versions from a Boss support page."""
        html = await self.fetch_page(firmware_page_url)
        if not html:
            return ScraperResult(
                success=False, error=f"Failed to fetch {firmware_page_url}"
            )

        soup = self.parse_html(html)
        firmware_versions = []

        # Boss pages typically show version like "[ Ver.1.10 ]" and dates like "JAN 2025"
        all_text = soup.get_text()

        # Look for version patterns: [ Ver.1.10 ] or Ver.1.10 or v1.10
        version_pattern = r"\[?\s*[Vv]er\.?\s*(\d+\.\d+(?:\.\d+)?)\s*\]?"

        # Look for download/update sections
        update_sections = soup.find_all(
            ["div", "section", "article", "tr", "li"],
            class_=re.compile(r"download|update|driver|firmware|item|content", re.I)
        )

        # Also check table rows for Boss's typical layout
        table_rows = soup.find_all("tr")

        for section in update_sections + table_rows:
            text = section.get_text()
            version_match = re.search(version_pattern, text)

            if version_match:
                version = version_match.group(1)

                # Find download link
                download_link = section.find("a", href=re.compile(r"\.(zip|exe|dmg|bin)", re.I))
                download_url = download_link["href"] if download_link else None
                if download_url and not download_url.startswith("http"):
                    download_url = f"https://www.boss.info{download_url}"

                # Boss uses month year format like "JAN 2025" or "FEB 2022"
                date_pattern = r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+(\d{4})"
                date_match = re.search(date_pattern, text, re.I)
                release_date = None
                if date_match:
                    month_str = date_match.group(1).upper()
                    year = int(date_match.group(2))
                    months = {
                        "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4,
                        "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8,
                        "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12
                    }
                    month = months.get(month_str, 1)
                    release_date = datetime(year, month, 1)

                # Also try "December 2023" format
                if not release_date:
                    long_date_pattern = r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})"
                    long_date_match = re.search(long_date_pattern, text, re.I)
                    if long_date_match:
                        try:
                            release_date = datetime.strptime(
                                f"{long_date_match.group(1)} {long_date_match.group(2)}",
                                "%B %Y"
                            )
                        except ValueError:
                            pass

                # Get changelog/notes
                changelog = None
                notes_section = section.find(["ul", "div", "p"], class_=re.compile(r"note|change|detail|description", re.I))
                if notes_section:
                    changelog = notes_section.get_text(strip=True)

                firmware_versions.append(
                    ScrapedFirmware(
                        version=version,
                        release_date=release_date,
                        download_url=download_url,
                        changelog=changelog,
                    )
                )

        # Deduplicate by version
        seen = set()
        unique = []
        for fw in firmware_versions:
            if fw.version not in seen:
                seen.add(fw.version)
                unique.append(fw)
        firmware_versions = unique

        # Fallback if no sections found
        if not firmware_versions:
            version_matches = re.findall(version_pattern, all_text)
            for version in set(version_matches):
                firmware_versions.append(ScrapedFirmware(version=version))

        return ScraperResult(success=True, firmware_versions=firmware_versions)
