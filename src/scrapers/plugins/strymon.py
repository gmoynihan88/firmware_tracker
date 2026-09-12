import re
from datetime import datetime
from typing import List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class StrymonScraper(BaseScraper):
    """Strymon pedals, read from the firmware notes on each support page.

    The previous parser looked for `firmware v1.49` and Strymon writes
    `BigSky Firmware Rev. 1.49 (Released March 2019):` -- the "Rev." between the two
    halves meant the pattern matched almost nothing. Fourteen of fifteen products
    stored no version at all, the fifteenth stored 1.42 for a Timeline that has been
    on 1.88 since 2020, and the scrape reported no failures throughout.

    The pages are fine and always were: BigSky returns 29,980 characters of text, and
    a support URL for a product name invented to test it 404s properly. This was only
    ever a parsing problem, which is unusual here -- normally it is a dead URL.

    Each page carries the full history with month-precision dates, stored as the first
    of the month. Archived releases are listed too and are kept: "no longer available
    for download" is a statement about the file, not about whether the release
    happened.
    """

    manufacturer_name = "Strymon"
    manufacturer_slug = "strymon"
    manufacturer_website = "https://www.strymon.net"

    SUPPORT_URL = "https://www.strymon.net/support/"
    PRODUCTS_URL = "https://www.strymon.net/products/"

    # Known Strymon products with their firmware pages
    KNOWN_PRODUCTS = [
        ("BigSky", "guitar_pedal", "https://www.strymon.net/support/bigsky/"),
        ("Timeline", "guitar_pedal", "https://www.strymon.net/support/timeline/"),
        ("Mobius", "guitar_pedal", "https://www.strymon.net/support/mobius/"),
        ("Iridium", "guitar_pedal", "https://www.strymon.net/support/iridium/"),
        ("Volante", "guitar_pedal", "https://www.strymon.net/support/volante/"),
        ("NightSky", "guitar_pedal", "https://www.strymon.net/support/nightsky/"),
        ("Cloudburst", "guitar_pedal", "https://www.strymon.net/support/cloudburst/"),
        ("Zelzah", "guitar_pedal", "https://www.strymon.net/support/zelzah/"),
        ("Brig", "guitar_pedal", "https://www.strymon.net/support/brig/"),
        ("DIG", "guitar_pedal", "https://www.strymon.net/support/dig/"),
        ("El Capistan", "guitar_pedal", "https://www.strymon.net/support/elcapistan/"),
        ("Flint", "guitar_pedal", "https://www.strymon.net/support/flint/"),
        ("Deco", "guitar_pedal", "https://www.strymon.net/support/deco/"),
        ("Riverside", "guitar_pedal", "https://www.strymon.net/support/riverside/"),
        ("Sunset", "guitar_pedal", "https://www.strymon.net/support/sunset/"),
    ]

    async def fetch_device_list(self) -> ScraperResult:
        """Return the list of known Strymon products."""
        devices = [
            ScrapedDevice(
                name=name,
                category=category,
                firmware_page_url=support_url,
                product_url=f"{self.PRODUCTS_URL}{name.lower().replace(' ', '')}/",
            )
            for name, category, support_url in self.KNOWN_PRODUCTS
        ]
        return ScraperResult(success=True, devices=devices)

    # Three spellings across the range, and the third is why NightSky looked like it
    # had no firmware at all:
    #   "BigSky Firmware Rev. 1.49 (Released March 2019):"
    #   "Firmware Rev. 1.23"                     -- no product name, no date
    #   "NightSky Firmware REV v1.07 (Released March 2021)"  -- a v before the digits
    #   "Sunset Firmware REV v 1.23 (Release August 2018)"    -- "Release", not "Released"
    #
    # "Firmware Rev" is still required. Sunset's page says "must have firmware version
    # 1.20 or later", which is a MIDI compatibility note rather than a release, and a
    # pattern accepting "firmware version" would report it as one.
    FIRMWARE = re.compile(
        r"Firmware\s+Rev(?:ision)?\.?\s*v?\s*(\d+(?:\.\d+)+)"
        r"(?:\s*\(\s*Released?\s+([A-Za-z]+)\s+(\d{4})\s*\))?",
        re.I,
    )
    MONTHS = {m.lower(): i for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"], start=1)}

    def _parse_firmware(self, html: str) -> List[ScrapedFirmware]:
        """Read the firmware revisions, newest first.

        Scanning the page text is safe here only because the pattern requires the
        words "Firmware Rev". The same pages carry Strymon's Nixie editor ("Nixie
        1.0", "Version: 0.9.4.3") and OS requirements ("Mac OS X - 10.6.8"), none of
        which a looser version pattern would tell apart.
        """
        text = re.sub(r"\s+", " ", self.parse_html(html).get_text(" "))

        versions: List[ScrapedFirmware] = []
        seen = set()

        for match in self.FIRMWARE.finditer(text):
            version, month, year = match.groups()
            if version in seen:
                continue
            seen.add(version)

            release_date = None
            if month and year:
                try:
                    release_date = datetime(int(year), self.MONTHS[month.lower()], 1)
                except (ValueError, KeyError):
                    release_date = None

            versions.append(ScrapedFirmware(version=version, release_date=release_date))

        return versions

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        html = await self.fetch_page(firmware_page_url)
        if not html:
            return ScraperResult(
                success=False, error=f"Failed to fetch {firmware_page_url}"
            )

        versions = self._parse_firmware(html)
        if not versions:
            # Some pedals are analogue or have never had an update. The page loaded,
            # so this is an absence rather than a failure.
            return ScraperResult(success=True, firmware_versions=[])

        return ScraperResult(success=True, firmware_versions=versions)
