import json
import re
from datetime import datetime
from typing import Optional, Union, List
from urllib.parse import parse_qs, urlparse

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class TCElectronicScraper(BaseScraper):
    """Scraper for TC Electronic guitar pedals and effects."""

    manufacturer_name = "TC Electronic"
    manufacturer_slug = "tcelectronic"
    manufacturer_website = "https://www.tcelectronic.com"

    # API endpoint for product downloads (Music Tribe platform)
    DOWNLOADS_API = "https://www.tcelectronic.com/.rest/api/v1/product/{model_code}/downloads"

    # Known TC Electronic products with firmware updates
    # Format: (name, category, product_page_url)
    KNOWN_PRODUCTS = [
        ("Ditto+", "guitar_pedal", "https://www.tcelectronic.com/product.html?modelCode=0709-AIU"),
        ("Ditto X4", "guitar_pedal", "https://www.tcelectronic.com/product.html?modelCode=0709-AGA"),
        ("Ditto Looper", "guitar_pedal", "https://www.tcelectronic.com/product.html?modelCode=P0CM7"),
        ("Flashback 2", "guitar_pedal", "https://www.tcelectronic.com/product.html?modelCode=P0DDD"),
        ("Hall of Fame 2", "guitar_pedal", "https://www.tcelectronic.com/product.html?modelCode=P0DDC"),
        ("Plethora X5", "guitar_pedal", "https://www.tcelectronic.com/product.html?modelCode=P0DQS"),
        ("Plethora X3", "guitar_pedal", "https://www.tcelectronic.com/product.html?modelCode=P0DWB"),
        ("PolyTune 3", "guitar_pedal", "https://www.tcelectronic.com/product.html?modelCode=P0DDG"),
    ]

    # Known firmware versions (fallback when dynamic scraping fails)
    # TC Electronic's site loads downloads via JavaScript, making scraping difficult
    # Format: model_code -> [(version, release_date, download_url, changelog)]
    KNOWN_FIRMWARE = {
        "0709-AIU": [  # Ditto+
            ("1.4", None, None, "Bug fixes and performance improvements"),
            ("1.3", None, None, None),
            ("1.2", None, None, None),
            ("1.1", None, None, None),
            ("1.0", None, None, "Initial release"),
        ],
        "0709-AGA": [  # Ditto X4
            ("1.2", None, None, None),
            ("1.1", None, None, None),
            ("1.0", None, None, "Initial release"),
        ],
    }

    def _extract_model_code(self, url: str) -> Optional[str]:
        """Extract modelCode from a TC Electronic product URL."""
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        model_codes = params.get("modelCode", [])
        return model_codes[0] if model_codes else None

    async def fetch_device_list(self) -> ScraperResult:
        """Return the list of known TC Electronic products."""
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

    async def _fetch_json(self, url: str) -> Optional[dict]:
        """Fetch JSON from a URL."""
        await self._rate_limit()
        session = await self._get_session()
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.json()
                return None
        except Exception:
            return None

    async def _try_api_fetch(self, model_code: str) -> List[ScrapedFirmware]:
        """Try to fetch firmware from Music Tribe API endpoints."""
        firmware_versions = []

        # Try various API endpoint patterns used by Music Tribe sites
        api_patterns = [
            f"https://www.tcelectronic.com/.rest/api/v1/product/{model_code}/downloads",
            f"https://www.tcelectronic.com/.rest/delivery/downloads/{model_code}",
            f"https://www.tcelectronic.com/api/downloads/{model_code}",
        ]

        for api_url in api_patterns:
            data = await self._fetch_json(api_url)
            if data and isinstance(data, (dict, list)):
                firmware_versions.extend(self._parse_api_response(data))
                if firmware_versions:
                    break

        return firmware_versions

    def _parse_api_response(self, data: Union[dict, list]) -> List[ScrapedFirmware]:
        """Parse firmware data from API response."""
        firmware_versions = []

        items = data if isinstance(data, list) else data.get("downloads", data.get("items", []))

        for item in items:
            if not isinstance(item, dict):
                continue

            # Look for firmware/software type entries
            item_type = item.get("type", "").lower()
            if item_type not in ("firmware", "software", ""):
                continue

            version = item.get("version") or item.get("name", "")
            version_match = re.search(r"(\d+\.\d+(?:\.\d+)?)", version)
            if not version_match:
                continue

            download_url = item.get("url") or item.get("downloadUrl") or item.get("href")
            release_date = None
            date_str = item.get("date") or item.get("releaseDate") or item.get("publishDate")
            if date_str:
                for fmt in ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y", "%m/%d/%Y"]:
                    try:
                        release_date = datetime.strptime(date_str[:10], fmt[:len(date_str[:10])])
                        break
                    except ValueError:
                        continue

            firmware_versions.append(
                ScrapedFirmware(
                    version=version_match.group(1),
                    release_date=release_date,
                    download_url=download_url,
                    changelog=item.get("description") or item.get("notes"),
                )
            )

        return firmware_versions

    def _extract_embedded_json(self, html: str) -> List[ScrapedFirmware]:
        """Extract firmware data from embedded JSON in page."""
        firmware_versions = []

        # Look for JSON data in script tags
        json_patterns = [
            r'window\.__INITIAL_STATE__\s*=\s*({.*?});',
            r'window\.productData\s*=\s*({.*?});',
            r'"downloads"\s*:\s*(\[.*?\])',
            r'"firmware"\s*:\s*(\[.*?\])',
        ]

        for pattern in json_patterns:
            matches = re.findall(pattern, html, re.DOTALL)
            for match in matches:
                try:
                    data = json.loads(match)
                    firmware_versions.extend(self._parse_api_response(data))
                except json.JSONDecodeError:
                    continue

        return firmware_versions

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        """Fetch firmware versions from a TC Electronic product page."""
        firmware_versions = []

        # Extract model code and try API first
        model_code = self._extract_model_code(firmware_page_url)
        if model_code:
            firmware_versions = await self._try_api_fetch(model_code)

        # TC Electronic uses JavaScript to load downloads - use Playwright
        # Click the download tab to load firmware content
        html = await self.fetch_page_js(
            firmware_page_url,
            click_selector="a[href*='downloads'], [data-tab*='download'], .tab-downloads",
            wait_for_timeout=15000,
        )
        # Fall back to static fetch if Playwright fails
        if not html:
            html = await self.fetch_page(firmware_page_url)
        if not html:
            if firmware_versions:
                return ScraperResult(success=True, firmware_versions=firmware_versions)
            return ScraperResult(
                success=False, error=f"Failed to fetch {firmware_page_url}"
            )

        # Try extracting from embedded JSON
        if not firmware_versions:
            firmware_versions = self._extract_embedded_json(html)

        # Fall back to HTML parsing
        if not firmware_versions:
            soup = self.parse_html(html)
            all_text = soup.get_text()

            # Normalize device name for matching (e.g., "Plethora X5" -> "PLETHORA X5")
            device_pattern = device_name.upper().replace("-", "").replace(" ", r"\s*")

            # TC Electronic format: "PRODUCT_NAMESoftwareFirmware Version 1.4.082021-11-12"
            # Look for product-specific versions - limit distance to 100 chars to avoid spanning products
            product_version_pattern = rf"{device_pattern}.{{0,100}}?[Vv]ersion\s*(\d+\.\d+(?:\.\d+)?)(\d{{4}}-\d{{2}}-\d{{2}})"
            for match in re.finditer(product_version_pattern, all_text):
                version = match.group(1)
                date_str = match.group(2)
                if not any(fw.version == version for fw in firmware_versions):
                    try:
                        release_date = datetime.strptime(date_str, "%Y-%m-%d")
                    except ValueError:
                        release_date = None
                    firmware_versions.append(
                        ScrapedFirmware(version=version, release_date=release_date)
                    )

            # Also try standard version pattern for other formats
            version_pattern = r"(?:[Vv](?:ersion)?|[Ff]irmware)\s*\.?\s*(\d+\.\d+(?:\.\d+)?)"

            # Look for download/support sections
            sections = soup.find_all(
                ["div", "section", "article", "li", "td"],
                class_=re.compile(r"download|support|firmware|software|update|version", re.I)
            )

            # Also check for download links
            download_links = soup.find_all("a", href=re.compile(r"download|firmware|update", re.I))

            # Check for mediadl.musictribe.com links (direct download CDN)
            cdn_links = soup.find_all("a", href=re.compile(r"mediadl\.musictribe\.com", re.I))
            for link in cdn_links:
                href = link.get("href", "")
                text = link.get_text() + " " + (link.get("title", "") or "")
                version_match = re.search(version_pattern, text + href)
                if version_match:
                    firmware_versions.append(
                        ScrapedFirmware(
                            version=version_match.group(1),
                            download_url=href,
                        )
                    )

            for section in sections:
                text = section.get_text()
                version_match = re.search(version_pattern, text)

                if version_match:
                    version = version_match.group(1)
                    if any(fw.version == version for fw in firmware_versions):
                        continue

                    # Find download link
                    download_link = section.find("a", href=re.compile(r"\.(zip|exe|dmg|bin)", re.I))
                    download_url = download_link["href"] if download_link else None
                    if download_url and not download_url.startswith("http"):
                        download_url = f"https://www.tcelectronic.com{download_url}"

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

            # Check download links directly
            for link in download_links:
                text = link.get_text() + " " + (link.get("title", "") or "")
                version_match = re.search(version_pattern, text)
                if version_match:
                    version = version_match.group(1)
                    if not any(fw.version == version for fw in firmware_versions):
                        download_url = link.get("href")
                        if download_url and not download_url.startswith("http"):
                            download_url = f"https://www.tcelectronic.com{download_url}"
                        firmware_versions.append(
                            ScrapedFirmware(version=version, download_url=download_url)
                        )

            # Fallback: scan entire page for version patterns
            if not firmware_versions:
                matches = re.findall(version_pattern, all_text)
                seen = set()
                for version in matches:
                    if version not in seen:
                        seen.add(version)
                        firmware_versions.append(ScrapedFirmware(version=version))

        # Deduplicate and filter malformed versions
        seen = set()
        unique = []
        for fw in firmware_versions:
            # Skip versions that have year appended (e.g., "1.4.082021")
            if re.match(r"^\d+\.\d+\.\d{6,}$", fw.version):
                continue
            if fw.version not in seen:
                seen.add(fw.version)
                unique.append(fw)

        # Fallback to known firmware if nothing found dynamically
        if not unique and model_code and model_code in self.KNOWN_FIRMWARE:
            for version, release_date, download_url, changelog in self.KNOWN_FIRMWARE[model_code]:
                unique.append(
                    ScrapedFirmware(
                        version=version,
                        release_date=release_date,
                        download_url=download_url,
                        changelog=changelog,
                    )
                )

        return ScraperResult(success=True, firmware_versions=unique)
