import re
from datetime import datetime
from typing import Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class Line6Scraper(BaseScraper):
    """Scraper for Line 6 guitar gear and wireless systems."""

    manufacturer_name = "Line 6"
    manufacturer_slug = "line6"
    manufacturer_website = "https://line6.com"

    # THR Remote page contains G10TII transmitter firmware (used by Relay G10II/G10S)
    THR_REMOTE_URL = "https://usa.yamaha.com/support/updates/thr_remote_mac.html"

    # Known Line 6 products with firmware updates
    KNOWN_PRODUCTS = [
        ("Relay G10II", "wireless_system", THR_REMOTE_URL),
        ("Relay G10S", "wireless_system", THR_REMOTE_URL),
        ("Helix", "guitar_pedal", "https://line6.com/support/page/kb/helix/"),
        ("Helix Floor", "guitar_pedal", "https://line6.com/support/page/kb/helix/"),
        ("Helix LT", "guitar_pedal", "https://line6.com/support/page/kb/helix/"),
        ("Helix Rack", "guitar_pedal", "https://line6.com/support/page/kb/helix/"),
        ("HX Stomp", "guitar_pedal", "https://line6.com/support/page/kb/helix/"),
        ("HX Stomp XL", "guitar_pedal", "https://line6.com/support/page/kb/helix/"),
        ("HX Effects", "guitar_pedal", "https://line6.com/support/page/kb/helix/"),
        ("POD Go", "guitar_pedal", "https://line6.com/support/page/kb/pod-go/"),
        ("POD Go Wireless", "guitar_pedal", "https://line6.com/support/page/kb/pod-go/"),
        ("Spider V 60", "guitar_pedal", "https://line6.com/support/page/kb/spider/"),
        ("Spider V 120", "guitar_pedal", "https://line6.com/support/page/kb/spider/"),
        ("Spider V 240", "guitar_pedal", "https://line6.com/support/page/kb/spider/"),
        ("Catalyst 60", "guitar_pedal", "https://line6.com/support/page/kb/catalyst/"),
        ("Catalyst 100", "guitar_pedal", "https://line6.com/support/page/kb/catalyst/"),
        ("Catalyst 200", "guitar_pedal", "https://line6.com/support/page/kb/catalyst/"),
    ]

    async def fetch_device_list(self) -> ScraperResult:
        """Return the list of known Line 6 products."""
        devices = [
            ScrapedDevice(
                name=name,
                category=category,
                firmware_page_url=url,
                product_url=f"https://line6.com/products/{name.lower().replace(' ', '-')}/",
            )
            for name, category, url in self.KNOWN_PRODUCTS
        ]
        return ScraperResult(success=True, devices=devices)

    def _parse_thr_remote_page(self, html: str) -> list[ScrapedFirmware]:
        """Parse G10TII transmitter firmware from Yamaha THR Remote page."""
        soup = self.parse_html(html)
        text = soup.get_text()
        firmware_versions = []

        # THR Remote page format: "[Firmware Ver.1.10 for THR30IIA Wireless]"
        # This is the G10TII transmitter firmware used in Relay G10II/G10S
        firmware_entries = re.findall(
            r"\[Firmware\s+Ver\.?\s*(\d+\.\d+)\s+for\s+THR30IIA\s+Wireless\]",
            text,
            re.I
        )

        for version in firmware_entries:
            firmware_versions.append(ScrapedFirmware(version=version))

        return firmware_versions

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        """Fetch firmware versions from Line 6 support pages."""
        # Relay G10II/G10S use G10TII transmitter firmware from Yamaha THR Remote page
        if "Relay G10" in device_name and "thr_remote" in firmware_page_url:
            html = await self.fetch_page_js(firmware_page_url, wait_for_timeout=15000)
            if html:
                firmware_versions = self._parse_thr_remote_page(html)
                if firmware_versions:
                    return ScraperResult(success=True, firmware_versions=firmware_versions)

        html = await self.fetch_page(firmware_page_url)
        if not html:
            return ScraperResult(
                success=False, error=f"Failed to fetch {firmware_page_url}"
            )

        soup = self.parse_html(html)
        firmware_versions = []
        all_text = soup.get_text()

        # Line 6 versions look like "v1.0.0" or "Version 3.70" or "Firmware 3.70"
        version_pattern = r"(?:[Vv](?:ersion)?|[Ff]irmware)\s*\.?\s*(\d+\.\d+(?:\.\d+)?)"

        # Look for firmware/download sections
        sections = soup.find_all(
            ["div", "section", "article", "li", "td", "p", "tr"],
            class_=re.compile(r"download|firmware|update|version|content|post|entry", re.I)
        )

        # Also look for links to downloads
        download_links = soup.find_all("a", href=re.compile(r"download|firmware|update", re.I))

        for section in sections:
            text = section.get_text()

            # Check if relevant to device (for multi-product pages)
            device_pattern = device_name.lower().replace(" ", "").replace("-", "")
            section_text = text.lower().replace(" ", "").replace("-", "")

            version_match = re.search(version_pattern, text)

            if version_match:
                version = version_match.group(1)

                # Find download link
                download_link = section.find("a", href=re.compile(r"\.(zip|exe|dmg|hxf|hlx)", re.I))
                download_url = download_link["href"] if download_link else None
                if download_url and not download_url.startswith("http"):
                    download_url = f"https://line6.com{download_url}"

                # Look for date
                date_patterns = [
                    r"(\w+)\s+(\d{1,2}),?\s+(\d{4})",  # Month DD, YYYY
                    r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})",  # MM/DD/YYYY
                    r"(\d{4})-(\d{2})-(\d{2})",  # YYYY-MM-DD
                ]
                release_date = None

                for pattern in date_patterns:
                    date_match = re.search(pattern, text)
                    if date_match:
                        groups = date_match.groups()
                        try:
                            if len(groups[0]) > 2:  # Month name or YYYY
                                if groups[0].isdigit():  # YYYY-MM-DD
                                    release_date = datetime(int(groups[0]), int(groups[1]), int(groups[2]))
                                else:  # Month DD, YYYY
                                    release_date = datetime.strptime(
                                        f"{groups[0]} {groups[1]} {groups[2]}".replace(",", ""),
                                        "%B %d %Y"
                                    )
                            else:  # MM/DD/YYYY
                                release_date = datetime(int(groups[2]), int(groups[0]), int(groups[1]))
                            break
                        except ValueError:
                            continue

                # Get changelog if available
                changelog = None
                changelog_section = section.find(["ul", "div"], class_=re.compile(r"change|note|detail", re.I))
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

        # Check download links
        for link in download_links:
            text = link.get_text() + " " + (link.get("title", "") or "")
            version_match = re.search(version_pattern, text)
            if version_match:
                version = version_match.group(1)
                if not any(fw.version == version for fw in firmware_versions):
                    download_url = link.get("href")
                    if download_url and not download_url.startswith("http"):
                        download_url = f"https://line6.com{download_url}"
                    firmware_versions.append(
                        ScrapedFirmware(version=version, download_url=download_url)
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
