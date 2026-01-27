import re
from datetime import datetime
from typing import Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class RolandScraper(BaseScraper):
    """Scraper for Roland synthesizers, grooveboxes, and music production gear."""

    manufacturer_name = "Roland"
    manufacturer_slug = "roland"
    manufacturer_website = "https://www.roland.com"

    # Known Roland products with firmware updates
    KNOWN_PRODUCTS = [
        ("MC-101", "synthesizer", "https://www.roland.com/global/support/by_product/mc-101/updates_drivers/"),
        ("MC-707", "synthesizer", "https://www.roland.com/global/support/by_product/mc-707/updates_drivers/"),
        ("SP-404MKII", "synthesizer", "https://www.roland.com/global/support/by_product/sp-404mk2/updates_drivers/"),
        ("VERSELAB MV-1", "synthesizer", "https://www.roland.com/global/support/by_product/verselab_mv-1/updates_drivers/"),
        ("JUPITER-X", "synthesizer", "https://www.roland.com/global/support/by_product/jupiter-x/updates_drivers/"),
        ("JUPITER-Xm", "synthesizer", "https://www.roland.com/global/support/by_product/jupiter-xm/updates_drivers/"),
        ("FANTOM-06", "synthesizer", "https://www.roland.com/global/support/by_product/fantom-06/updates_drivers/"),
        ("FANTOM-07", "synthesizer", "https://www.roland.com/global/support/by_product/fantom-07/updates_drivers/"),
        ("FANTOM-08", "synthesizer", "https://www.roland.com/global/support/by_product/fantom-08/updates_drivers/"),
        ("RD-88", "synthesizer", "https://www.roland.com/global/support/by_product/rd-88/updates_drivers/"),
        ("JUNO-DS61", "synthesizer", "https://www.roland.com/global/support/by_product/juno-ds61/updates_drivers/"),
        ("TR-6S", "synthesizer", "https://www.roland.com/global/support/by_product/tr-6s/updates_drivers/"),
        ("TR-8S", "synthesizer", "https://www.roland.com/global/support/by_product/tr-8s/updates_drivers/"),
        ("J-6", "synthesizer", "https://www.roland.com/global/support/by_product/j-6/updates_drivers/"),
        ("T-8", "synthesizer", "https://www.roland.com/global/support/by_product/t-8/updates_drivers/"),
        ("SE-02", "synthesizer", "https://www.roland.com/global/support/by_product/se-02/updates_drivers/"),
    ]

    async def fetch_device_list(self) -> ScraperResult:
        """Return the list of known Roland products."""
        devices = [
            ScrapedDevice(
                name=name,
                category=category,
                firmware_page_url=url,
                product_url=url.replace("/support/by_product/", "/products/").replace("/updates_drivers/", "/"),
            )
            for name, category, url in self.KNOWN_PRODUCTS
        ]
        return ScraperResult(success=True, devices=devices)

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        """Fetch firmware versions from a Roland support page."""
        html = await self.fetch_page(firmware_page_url)
        if not html:
            return ScraperResult(
                success=False, error=f"Failed to fetch {firmware_page_url}"
            )

        soup = self.parse_html(html)
        firmware_versions = []
        all_text = soup.get_text()

        # Roland versions look like "Ver.1.72" or "Version 1.72" or "v1.72"
        version_pattern = r"[Vv](?:er\.?|ersion)?\s*(\d+\.\d+(?:\.\d+)?)"

        # Roland support pages typically have download items in lists or tables
        sections = soup.find_all(
            ["div", "section", "article", "li", "tr", "td"],
            class_=re.compile(r"download|update|driver|firmware|item|content|list", re.I)
        )

        for section in sections:
            text = section.get_text()
            version_match = re.search(version_pattern, text)

            if version_match:
                version = version_match.group(1)

                # Find download link
                download_link = section.find("a", href=re.compile(r"\.(zip|exe|dmg|bin)", re.I))
                download_url = download_link["href"] if download_link else None
                if download_url and not download_url.startswith("http"):
                    download_url = f"https://www.roland.com{download_url}"

                # Roland uses various date formats
                date_patterns = [
                    r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[.\s]+(\d{4})",
                    r"(\d{4})[/-](\d{2})[/-](\d{2})",
                    r"(\w+)\s+(\d{1,2}),?\s+(\d{4})",
                ]
                release_date = None

                # Try month-year format (e.g., "JAN. 2024")
                month_year_match = re.search(date_patterns[0], text, re.I)
                if month_year_match:
                    months = {
                        "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4,
                        "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8,
                        "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12
                    }
                    month = months.get(month_year_match.group(1).upper(), 1)
                    year = int(month_year_match.group(2))
                    release_date = datetime(year, month, 1)

                # Try ISO date format
                if not release_date:
                    iso_match = re.search(date_patterns[1], text)
                    if iso_match:
                        try:
                            year, month, day = iso_match.groups()
                            release_date = datetime(int(year), int(month), int(day))
                        except ValueError:
                            pass

                # Get changelog/notes
                changelog = None
                notes_elem = section.find(["ul", "div", "p"], class_=re.compile(r"note|change|detail", re.I))
                if notes_elem:
                    changelog = notes_elem.get_text(strip=True)[:500]

                firmware_versions.append(
                    ScrapedFirmware(
                        version=version,
                        release_date=release_date,
                        download_url=download_url,
                        changelog=changelog,
                    )
                )

        # Deduplicate
        seen = set()
        unique = []
        for fw in firmware_versions:
            if fw.version not in seen:
                seen.add(fw.version)
                unique.append(fw)
        firmware_versions = unique

        # Fallback: scan entire page
        if not firmware_versions:
            matches = re.findall(version_pattern, all_text)
            seen = set()
            for version in matches:
                if version not in seen:
                    seen.add(version)
                    firmware_versions.append(ScrapedFirmware(version=version))

        return ScraperResult(success=True, firmware_versions=firmware_versions)
