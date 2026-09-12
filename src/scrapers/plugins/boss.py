import re
from datetime import datetime
from typing import Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult
from src.scrapers.roland_group import SystemProgramMixin


class BossScraper(SystemProgramMixin, BaseScraper):
    """Boss pedals, read the same way as Roland because it is the same site.

    Boss is a Roland brand and its Updates & Drivers pages are identical in shape, so
    the parsing lives in SystemProgramMixin and both use it.

    The previous parser searched the listing for a date in two formats and found none,
    because that page has no dates at all -- 3,656 characters of text and not one.
    The dates are on the detail page behind the System Program link, along with the
    rest of the history. It also had to guess which version on the page was the
    firmware, competing with an IR Loader, four USB drivers and a bundled copy of
    Chromium Embedded Framework.
    """

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
        ("Katana-100 MkII", "guitar_pedal", "https://www.boss.info/us/support/by_product/katana-100_mk2/updates_drivers/"),
        ("Katana-Artist MkII", "guitar_pedal", "https://www.boss.info/us/support/by_product/katana-artist_mk2/updates_drivers/"),
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
        versions, error = await self._fetch_system_program(firmware_page_url)
        if error:
            return ScraperResult(success=False, error=error)
        return ScraperResult(success=True, firmware_versions=versions)
