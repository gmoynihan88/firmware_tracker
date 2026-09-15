import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class Line6Scraper(BaseScraper):
    """Scraper for Line 6 guitar processors and amplifiers.

    Every firmware release Line 6 has ever shipped is listed on one page, each entry
    naming the products it applies to. That page is fetched once per scrape and the
    result reused, rather than fetched per device.

    The products are the ones that page names. They were a hand-kept list of 17 until
    2026-09-15, while the page named 131 across 413 releases -- the current Catalyst
    CX, POD Express and DL4 MkII among them, and the whole POD HD, Spider IV, Variax
    and Relay back catalogue. The page's own hardware filter is not used: it is one
    flat list that also offers things with no release at all ("No Hardware Required",
    iLok, Helix Stadium), and it omits 21 products that have releases.

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

    # The page's name -> the database's, for rows catalogued under another name. The
    # G10II ships its firmware as the G10TII transmitter and the G10S as its receiver;
    # the G10II was previously read off Yamaha's THR Remote page, which publishes THR
    # amp firmware and not the transmitter's.
    RENAMES = {
        "Relay G10TII Transmitter": "Relay G10II",
        "Relay G10S Receiver": "Relay G10S",
    }

    # Rows that read another product's releases as well as that product's own row.
    # Line 6 sells the Helix Floor and lists its releases as "Helix"; both rows exist.
    ALSO_LISTED_AS = {"Helix": ["Helix Floor"]}

    # Line 6 publishes no categories, so they come from the name. Checked in order, so
    # the floor processors among the amp families are caught first. Anything
    # unmatched -- POD, Helix, HX, the M-series, DL4 -- is a processor, filed as a
    # pedal. Only used when a row is created.
    CATEGORIES = [
        (("AMPLIFi FX100", "Firehawk FX"), "guitar_pedal"),
        (("Spider", "Catalyst", "AMPLIFi", "DT25", "DT50", "Firehawk", "Flextone",
          "Powercab", "Vetta", "StageScape", "StageSource", "Relay", "XD-V", "Variax",
          "James Tyler Variax", "BackTrack"), "other"),
        (("FBV", "Mobile Keys"), "midi_controller"),
        (("TonePort", "POD Studio"), "audio_interface"),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._catalogue: Optional[Dict[str, List[ScrapedFirmware]]] = None

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(p) for p in re.findall(r"\d+", version)) or (0,)

    def _category(self, name: str) -> str:
        for prefixes, category in self.CATEGORIES:
            if name.startswith(prefixes):
                return category
        return "guitar_pedal"

    def _page_name(self, device_name: str) -> str:
        """The name the page lists a device's releases under."""
        for page_name, renamed in self.RENAMES.items():
            if renamed == device_name:
                return page_name
        for page_name, aliases in self.ALSO_LISTED_AS.items():
            if device_name in aliases:
                return page_name
        return device_name

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
        catalogue = await self._get_catalogue()
        if catalogue is None:
            return ScraperResult(
                success=False,
                error=f"Could not read the Line 6 firmware listing at {self.FIRMWARE_URL}",
            )

        devices = []
        for product in catalogue:
            for name in [self.RENAMES.get(product, product), *self.ALSO_LISTED_AS.get(product, [])]:
                devices.append(
                    ScrapedDevice(
                        name=name,
                        category=self._category(name),
                        firmware_page_url=self.FIRMWARE_URL,
                        product_url=self.FIRMWARE_URL,
                    )
                )
        return ScraperResult(success=True, devices=devices)

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        catalogue = await self._get_catalogue()
        if catalogue is None:
            return ScraperResult(
                success=False,
                error=f"Could not read the Line 6 firmware listing at {self.FIRMWARE_URL}",
            )

        page_name = self._page_name(device_name)
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
