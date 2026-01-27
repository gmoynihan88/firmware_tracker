import re
from datetime import datetime
from typing import Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class YamahaScraper(BaseScraper):
    """Scraper for Yamaha guitars, amps, and music production gear."""

    manufacturer_name = "Yamaha"
    manufacturer_slug = "yamaha"
    manufacturer_website = "https://usa.yamaha.com"

    # Known Yamaha products with firmware updates
    KNOWN_PRODUCTS = [
        ("THR30II Wireless", "guitar_pedal", "https://usa.yamaha.com/support/updates/thr30ii_wireless_firm.html"),
        ("THR30II", "guitar_pedal", "https://usa.yamaha.com/support/updates/thr30ii_firm.html"),
        ("THR10II Wireless", "guitar_pedal", "https://usa.yamaha.com/support/updates/thr10ii_wireless_firm.html"),
        ("THR10II", "guitar_pedal", "https://usa.yamaha.com/support/updates/thr10ii_firm.html"),
        ("MODX8", "synthesizer", "https://usa.yamaha.com/support/updates/modx8_firm.html"),
        ("MODX7", "synthesizer", "https://usa.yamaha.com/support/updates/modx7_firm.html"),
        ("MODX6", "synthesizer", "https://usa.yamaha.com/support/updates/modx6_firm.html"),
        ("Montage M8x", "synthesizer", "https://usa.yamaha.com/support/updates/montagem8x_firm.html"),
        ("Montage M7", "synthesizer", "https://usa.yamaha.com/support/updates/montagem7_firm.html"),
        ("Montage M6", "synthesizer", "https://usa.yamaha.com/support/updates/montagem6_firm.html"),
        ("SEQTRAK", "synthesizer", "https://usa.yamaha.com/support/updates/seqtrak_firm.html"),
        ("reface CS", "synthesizer", "https://usa.yamaha.com/support/updates/reface_cs_firm.html"),
        ("reface DX", "synthesizer", "https://usa.yamaha.com/support/updates/reface_dx_firm.html"),
        ("reface CP", "synthesizer", "https://usa.yamaha.com/support/updates/reface_cp_firm.html"),
        ("reface YC", "synthesizer", "https://usa.yamaha.com/support/updates/reface_yc_firm.html"),
    ]

    async def fetch_device_list(self) -> ScraperResult:
        """Return the list of known Yamaha products."""
        devices = [
            ScrapedDevice(
                name=name,
                category=category,
                firmware_page_url=url,
                product_url=url.replace("/support/updates/", "/products/").replace("_firm.html", "/"),
            )
            for name, category, url in self.KNOWN_PRODUCTS
        ]
        return ScraperResult(success=True, devices=devices)

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        """Fetch firmware versions from Yamaha support pages."""
        html = await self.fetch_page(firmware_page_url)
        if not html:
            return ScraperResult(
                success=False, error=f"Failed to fetch {firmware_page_url}"
            )

        soup = self.parse_html(html)
        firmware_versions = []
        all_text = soup.get_text()

        # Yamaha versions look like "V1.20" or "Ver.1.20" or "Version 1.20"
        version_pattern = r"[Vv](?:er\.?|ersion)?\s*(\d+\.\d+(?:\.\d+)?)"

        # Yamaha support pages have structured download sections
        sections = soup.find_all(
            ["div", "section", "article", "tr", "li", "td"],
            class_=re.compile(r"download|firmware|update|version|content", re.I)
        )

        # Also look at table rows
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            sections.extend(rows)

        for section in sections:
            text = section.get_text()
            version_match = re.search(version_pattern, text)

            if version_match:
                version = version_match.group(1)

                # Find download link
                download_link = section.find("a", href=re.compile(r"\.(zip|exe|dmg|bin)", re.I))
                download_url = download_link["href"] if download_link else None
                if download_url and not download_url.startswith("http"):
                    download_url = f"https://usa.yamaha.com{download_url}"

                # Yamaha uses various date formats
                date_patterns = [
                    (r"(\w+)\s+(\d{1,2}),?\s+(\d{4})", "%B %d %Y"),  # Month DD, YYYY
                    (r"(\d{4})[/-](\d{2})[/-](\d{2})", "%Y-%m-%d"),  # YYYY-MM-DD
                    (r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", None),    # MM/DD/YYYY or DD/MM/YYYY
                ]
                release_date = None

                for pattern, fmt in date_patterns:
                    date_match = re.search(pattern, text)
                    if date_match:
                        try:
                            if fmt:
                                date_str = " ".join(date_match.groups())
                                release_date = datetime.strptime(date_str.replace(",", ""), fmt)
                            else:
                                # Assume MM/DD/YYYY for US site
                                m, d, y = date_match.groups()
                                release_date = datetime(int(y), int(m), int(d))
                            break
                        except ValueError:
                            continue

                # Get changelog/notes
                changelog = None
                notes_elem = section.find(["ul", "div", "p"], class_=re.compile(r"note|change|detail|description", re.I))
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
