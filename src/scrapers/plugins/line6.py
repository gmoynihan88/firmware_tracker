import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class Line6Scraper(BaseScraper):
    """Scraper for Line 6 guitar processors and amplifiers.

    Every firmware release Line 6 has ever shipped is listed on one page, each entry
    naming the products it applies to. That page is fetched once per scrape and the
    result reused, rather than fetched per device.

    The previous /support/page/kb/<product>/ URLs are all dead. They return HTTP 200
    with a soft-404 body -- "Sorry, we could not find that!" -- which contains neither
    "404" nor "not found", so it reads as a successful fetch of an empty page.
    """

    manufacturer_name = "Line 6"
    manufacturer_slug = "line6"
    manufacturer_website = "https://line6.com"

    FIRMWARE_URL = "https://line6.com/software/Firmware"

    # Entries look like:
    #   <div class="release-details"><div class="sidebar">
    #     <b>Version 3.83</b><br><b>Released 10/28/25</b><br><br>
    #     Works with:<br><b>HX One</b>
    VERSION_LINE = re.compile(r"^Version\s+(\d+(?:\.\d+)+)")
    RELEASED_LINE = re.compile(r"^Released\s+(\d{1,2})/(\d{1,2})/(\d{2,4})")

    # (name, category, firmware_page_url)
    KNOWN_PRODUCTS = [
        ("Helix", "guitar_pedal", FIRMWARE_URL),
        ("Helix Floor", "guitar_pedal", FIRMWARE_URL),
        ("Helix LT", "guitar_pedal", FIRMWARE_URL),
        ("Helix Rack", "guitar_pedal", FIRMWARE_URL),
        ("HX Stomp", "guitar_pedal", FIRMWARE_URL),
        ("HX Stomp XL", "guitar_pedal", FIRMWARE_URL),
        ("HX Effects", "guitar_pedal", FIRMWARE_URL),
        ("POD Go", "guitar_pedal", FIRMWARE_URL),
        ("POD Go Wireless", "guitar_pedal", FIRMWARE_URL),
        ("Spider V 60", "other", FIRMWARE_URL),
        ("Spider V 120", "other", FIRMWARE_URL),
        ("Spider V 240", "other", FIRMWARE_URL),
        ("Catalyst 60", "other", FIRMWARE_URL),
        ("Catalyst 100", "other", FIRMWARE_URL),
        ("Catalyst 200", "other", FIRMWARE_URL),
        ("Relay G10II", "other", FIRMWARE_URL),
        ("Relay G10S", "other", FIRMWARE_URL),
    ]

    # Our device names against the ones Line 6 lists releases under. The G10II ships
    # its firmware as the G10TII transmitter; previously this was read off Yamaha's
    # THR Remote page, which publishes THR amp firmware and not the transmitter's.
    PAGE_NAMES = {
        "Helix Floor": "Helix",
        "Relay G10II": "Relay G10TII Transmitter",
        "Relay G10S": "Relay G10S Receiver",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._catalogue: Optional[Dict[str, List[ScrapedFirmware]]] = None

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(p) for p in re.findall(r"\d+", version)) or (0,)

    def _parse_catalogue(self, html: str) -> Dict[str, List[ScrapedFirmware]]:
        """Build a product -> releases map from the firmware listing.

        Only the sidebar's bold elements are read. The descriptions quote version
        numbers in prose ("3.50 renames the Impulse Response > Mono subcategory"),
        so scanning the text would invent releases that were never published.
        """
        catalogue: Dict[str, List[Tuple[tuple, ScrapedFirmware]]] = {}

        for entry in self.parse_html(html).find_all("div", class_="release-details"):
            sidebar = entry.find("div", class_="sidebar")
            if not sidebar:
                continue

            bolds = [b.get_text(" ", strip=True) for b in sidebar.find_all("b")]
            if not bolds:
                continue

            version_match = self.VERSION_LINE.match(bolds[0])
            if not version_match:
                continue
            version = version_match.group(1)

            release_date = None
            products = []
            for bold in bolds[1:]:
                released = self.RELEASED_LINE.match(bold)
                if released:
                    month, day, year = released.groups()
                    try:
                        release_date = datetime(2000 + int(year[-2:]), int(month), int(day))
                    except ValueError:
                        release_date = None
                else:
                    products.append(bold)

            description = entry.find("div", class_="description")
            changelog = description.get_text(" ", strip=True)[:500] if description else None

            for product in products:
                firmware = ScrapedFirmware(
                    version=version,
                    release_date=release_date,
                    download_url=self.FIRMWARE_URL,
                    changelog=changelog,
                )
                catalogue.setdefault(product, []).append((self._version_key(version), firmware))

        return {
            product: [fw for _key, fw in sorted(entries, key=lambda e: e[0], reverse=True)]
            for product, entries in catalogue.items()
        }

    async def _get_catalogue(self) -> Optional[Dict[str, List[ScrapedFirmware]]]:
        """Fetch and parse the firmware listing once per scraper instance."""
        if self._catalogue is not None:
            return self._catalogue

        # aiohttp is blocked by this host; the rendered page is the only route in.
        html = await self.fetch_page_js(self.FIRMWARE_URL, wait_for_timeout=25000)
        if not html:
            return None

        parsed = self._parse_catalogue(html)
        if not parsed:
            return None

        self._catalogue = parsed
        return self._catalogue

    async def fetch_device_list(self) -> ScraperResult:
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category=category,
                    firmware_page_url=url,
                    product_url=url,
                )
                for name, category, url in self.KNOWN_PRODUCTS
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        catalogue = await self._get_catalogue()
        if catalogue is None:
            return ScraperResult(
                success=False,
                error=f"Could not read the Line 6 firmware listing at {self.FIRMWARE_URL}",
            )

        page_name = self.PAGE_NAMES.get(device_name, device_name)
        releases = catalogue.get(page_name)
        if not releases:
            return ScraperResult(
                success=False,
                error=(
                    f"{device_name} is not listed on the Line 6 firmware page "
                    f"(looked for {page_name!r})"
                ),
            )

        return ScraperResult(success=True, firmware_versions=releases)
