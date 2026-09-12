import re
from datetime import datetime
from urllib.parse import urljoin
from typing import List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class RolandScraper(BaseScraper):
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

    # Roland writes this three ways, and requiring the parentheses silently dropped
    # the AIRA Compacts, which use the bare form:
    #   "MC-101 System Program (Ver.1.82)"
    #   "JUPITER-X System Program ( Ver.3.03 )"
    #   "J-6 System Program Ver.1.02"
    SYSTEM_PROGRAM = re.compile(
        r"System\s+Program\s*\(?\s*Ver\.?\s*(\d+(?:\.\d+)+)\s*\)?", re.I
    )

    # "[ Ver.1.82 ] JUN 2023"
    HISTORY_ENTRY = re.compile(
        r"\[\s*Ver\.?\s*(\d+(?:\.\d+)+)\s*\]\s*"
        r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\.?\s+(\d{4})",
        re.I,
    )
    MONTHS = {m: i for i, m in enumerate(
        ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
         "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)}

    def _system_program_link(self, html: str) -> Optional[tuple]:
        """Find the System Program entry, ignoring the driver downloads beside it."""
        soup = self.parse_html(html)
        for anchor in soup.find_all("a", href=True):
            match = self.SYSTEM_PROGRAM.search(anchor.get_text(" ", strip=True))
            if match:
                return match.group(1), urljoin(self.manufacturer_website, anchor["href"])
        return None

    def _parse_history(self, html: str) -> List[ScrapedFirmware]:
        """Read UPDATE HISTORY from the detail page.

        Scoped to the details container rather than the whole document: the page also
        explains how to check your current version, and that prose mentions version
        numbers that are not releases.
        """
        soup = self.parse_html(html)
        container = soup.select_one("div.details") or soup
        text = re.sub(r"\s+", " ", container.get_text(" "))

        entries = list(self.HISTORY_ENTRY.finditer(text))
        versions: List[ScrapedFirmware] = []

        for index, match in enumerate(entries):
            version, month, year = match.groups()
            try:
                release_date = datetime(int(year), self.MONTHS[month.upper()[:3]], 1)
            except (ValueError, KeyError):
                release_date = None

            end = entries[index + 1].start() if index + 1 < len(entries) else len(text)
            changelog = text[match.end():end].strip()[:500] or None

            versions.append(
                ScrapedFirmware(
                    version=version, release_date=release_date, changelog=changelog
                )
            )

        return versions

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        html = await self.fetch_page(firmware_page_url)
        if not html:
            return ScraperResult(
                success=False, error=f"Failed to fetch {firmware_page_url}"
            )

        found = self._system_program_link(html)
        if not found:
            # Roland keeps Updates & Drivers pages for products that only ever had
            # drivers. Reporting no firmware is right; reporting a driver version as
            # the instrument's would not be.
            return ScraperResult(success=True, firmware_versions=[])

        listed_version, detail_url = found

        detail = await self.fetch_page(detail_url)
        if detail:
            history = self._parse_history(detail)
            if history:
                return ScraperResult(success=True, firmware_versions=history)

        # The detail page exists but had no history block, so keep what the listing
        # stated rather than losing the version entirely.
        return ScraperResult(
            success=True,
            firmware_versions=[ScrapedFirmware(version=listed_version)],
        )
