import re
from datetime import datetime
from urllib.parse import urljoin
from typing import List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult
from src.scrapers.roland_group import SystemProgramMixin


class RolandScraper(SystemProgramMixin, BaseScraper):
    """Roland instruments, read from each product's System Program page.

    The Updates & Drivers listing carries two kinds of version and the previous
    parser could not tell them apart. Alongside "MC-101 System Program (Ver.1.82)",
    which is the instrument's firmware, sit half a dozen USB driver entries --
    "MC-101 Driver Ver.1.0.3 for macOS Sonoma 14.x or later" -- and a pattern
    scanning for the first `Ver.` on the page can land on either.

    That listing has no dates at all. The System Program entry links to a detail page
    that does, holding the full history rather than only the current release:

        [ Ver.1.82 ] JUN 2023
        Bug Fixes ...
        [ Ver.1.81 ] NOV 2022

    So each product costs one extra fetch, and yields every version Roland has
    published for it with a date and its changelog, where before it yielded one
    undated version.

    Roland dates to the month. These are stored as the first of that month, which is
    the usual way to record month precision -- worth knowing before reading a day
    number as exact.

    Versions are genuinely shared across a platform family: MC-101, MC-707 and
    VERSELAB MV-1 all run System Program 1.82. That is not the duplication bug it
    resembles; it was checked against all three pages.
    """

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
        versions, error = await self._fetch_system_program(firmware_page_url)
        if error:
            return ScraperResult(success=False, error=error)
        return ScraperResult(success=True, firmware_versions=versions)
