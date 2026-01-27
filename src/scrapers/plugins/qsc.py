import re
from datetime import datetime
from typing import Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class QSCScraper(BaseScraper):
    """Scraper for QSC powered speakers and audio equipment."""

    manufacturer_name = "QSC"
    manufacturer_slug = "qsc"
    manufacturer_website = "https://www.qsc.com"

    # Known QSC products with firmware updates
    KNOWN_PRODUCTS = [
        ("K12.2", "audio_interface", "https://www.qsc.com/resource-files/productresources/spk/k.2/firmware/"),
        ("K10.2", "audio_interface", "https://www.qsc.com/resource-files/productresources/spk/k.2/firmware/"),
        ("K8.2", "audio_interface", "https://www.qsc.com/resource-files/productresources/spk/k.2/firmware/"),
        ("KS212C", "audio_interface", "https://www.qsc.com/resource-files/productresources/spk/ks/firmware/"),
        ("KS118", "audio_interface", "https://www.qsc.com/resource-files/productresources/spk/ks/firmware/"),
        ("CP12", "audio_interface", "https://www.qsc.com/support/software-firmware/"),
        ("CP8", "audio_interface", "https://www.qsc.com/support/software-firmware/"),
        ("KLA12", "audio_interface", "https://www.qsc.com/support/software-firmware/"),
        ("TouchMix-30 Pro", "audio_interface", "https://www.qsc.com/support/software-firmware/touchmix-series/"),
        ("TouchMix-16", "audio_interface", "https://www.qsc.com/support/software-firmware/touchmix-series/"),
        ("TouchMix-8", "audio_interface", "https://www.qsc.com/support/software-firmware/touchmix-series/"),
    ]

    FIRMWARE_PAGE = "https://www.qsc.com/support/software-firmware/"

    async def fetch_device_list(self) -> ScraperResult:
        """Return the list of known QSC products."""
        devices = [
            ScrapedDevice(
                name=name,
                category=category,
                firmware_page_url=url,
                product_url=f"https://www.qsc.com/products-solutions/loudspeakers/{name.lower().replace(' ', '-').replace('.', '')}/",
            )
            for name, category, url in self.KNOWN_PRODUCTS
        ]
        return ScraperResult(success=True, devices=devices)

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        """Fetch firmware versions from QSC support pages."""
        html = await self.fetch_page(firmware_page_url)

        # Also try main firmware page
        main_html = await self.fetch_page(self.FIRMWARE_PAGE)

        if not html and not main_html:
            return ScraperResult(
                success=False, error=f"Failed to fetch firmware info"
            )

        firmware_versions = []

        for page_html in [html, main_html]:
            if not page_html:
                continue

            soup = self.parse_html(page_html)
            all_text = soup.get_text()

            # QSC versions look like "v1.0.0" or "Version 1.0.0" or "V1.0"
            version_pattern = r"[Vv](?:ersion)?\s*\.?\s*(\d+\.\d+(?:\.\d+)?)"

            # Look for download sections
            sections = soup.find_all(
                ["div", "section", "article", "li", "td", "tr", "p"],
                class_=re.compile(r"download|firmware|update|version|resource", re.I)
            )

            # Also look for links to firmware files
            download_links = soup.find_all("a", href=re.compile(r"\.(zip|exe|bin|qfw)", re.I))

            for section in sections:
                text = section.get_text()

                # Check if relevant to device
                device_pattern = device_name.lower().replace(".", "").replace(" ", "").replace("-", "")
                section_lower = text.lower().replace(".", "").replace(" ", "").replace("-", "")

                if device_pattern not in section_lower and device_name.split(".")[0].lower() not in text.lower():
                    continue

                version_match = re.search(version_pattern, text)

                if version_match:
                    version = version_match.group(1)

                    # Find download link
                    download_link = section.find("a", href=re.compile(r"\.(zip|exe|bin|qfw)", re.I))
                    download_url = download_link["href"] if download_link else None
                    if download_url and not download_url.startswith("http"):
                        download_url = f"https://www.qsc.com{download_url}"

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

            # Check download links for K.2 series (shared firmware)
            for link in download_links:
                href = link.get("href", "")
                text = link.get_text() + " " + (link.get("title", "") or "")
                parent_text = link.parent.get_text() if link.parent else ""
                combined = text + " " + parent_text + " " + href

                # K.2 series shares firmware
                if "k.2" in combined.lower() or "k2" in combined.lower():
                    if device_name.startswith("K") and device_name.endswith(".2"):
                        version_match = re.search(version_pattern, combined)
                        if version_match:
                            version = version_match.group(1)
                            if not any(fw.version == version for fw in firmware_versions):
                                download_url = href
                                if not download_url.startswith("http"):
                                    download_url = f"https://www.qsc.com{download_url}"
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

        return ScraperResult(success=True, firmware_versions=unique)
