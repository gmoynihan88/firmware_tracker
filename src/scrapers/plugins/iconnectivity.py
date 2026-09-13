import re
import unicodedata
from datetime import datetime
from typing import Dict, List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class IConnectivityScraper(BaseScraper):
    """iConnectivity, read from the firmware grid on its downloads page.

    One page, one fetch, 18 products each with a version and a release date:

        Product           Version & Date                Release Notes
        PlayAUDIO2U       Version 1.0.3 - Aug 19, 2026  Release Notes
        mioXL             Version 2.4.1 - Aug 17, 2025  Release Notes

    **It only looks like a table.** The page is Squarespace and the grid is three
    `div.col` siblings, each holding a `<p>` per row -- there is no `<table>` element
    on the page at all. Flattened to text the columns come out whole and consecutive:
    eighteen product names, then eighteen versions. Any pattern reading the text in
    order pairs PlayAUDIO2U with PlayAUDIO1U, and the first version with the
    nineteenth line. The columns are read separately and zipped by position, which is
    the only thing the markup supports.

    That positional pairing is safe here only because the columns are the same length
    and one of them proves it: the third row's product cell is `mioXL ﻿`, a
    zero-width no-break space Squarespace left behind, and a parser that skipped
    blank-looking cells in one column would shift every later row by one. Cells are
    taken as they come and normalised afterwards.

    **The page is mostly manual revisions.** Above the firmware grid sit more than
    twenty entries reading "Owner's manual version 1.3", "User Guide version 1.0",
    and a "Common System Exclusive Commands / Version 26". Every one is version-shaped
    and none is firmware, which is why this reads the grid rather than the page.

    Dates are "Aug 19, 2026" -- month abbreviated, and parsed by the month's first
    three letters rather than handed to a single strptime format, so the pattern
    cannot accept a spelling the parser then rejects.
    """

    manufacturer_name = "iConnectivity"
    manufacturer_slug = "iconnectivity"
    manufacturer_website = "https://www.iconnectivity.com"

    DOWNLOADS_URL = "https://www.iconnectivity.com/downloads"

    # "Version 1.0.3 - Aug 19, 2026"
    VERSION_AND_DATE = re.compile(
        r"Version\s+(\d+(?:\.\d+)+)\s*[-–—]\s*"
        r"([A-Z][a-z]{2})[a-z]*\.?\s+(\d{1,2}),\s+(\d{4})",
        re.I,
    )
    MONTHS = {month: index for index, month in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun",
         "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

    # Everything iConnectivity sells is a MIDI or audio interface; the grid carries
    # no category of its own, so the product name decides.
    AUDIO_WORDS = ("audio",)

    # The page has two grids of identical shape. Only the one under "Firmware" holds
    # products; the other sits under "Windows Drivers" and offered "Unified USB driver
    # for all current iConnectivity products, Version 6.0" as a device.
    FIRMWARE_SECTION = "firmware"

    # The grid's own column headers, skipped when looking back for the section label
    # -- the nearest heading above a grid is "Release Notes", its third column.
    COLUMN_HEADERS = {"product", "version & date", "version and date", "release notes"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._firmware: Optional[Dict[str, ScrapedFirmware]] = None

    @staticmethod
    def _clean(text: str) -> str:
        """Strip the zero-width characters Squarespace leaves in cells."""
        text = unicodedata.normalize("NFKC", text)
        for invisible in ("﻿", "​", "‌", "‍"):
            text = text.replace(invisible, "")
        return " ".join(text.split())

    def _category_for(self, name: str) -> str:
        lowered = name.lower()
        if any(word in lowered for word in self.AUDIO_WORDS):
            return "audio_interface"
        return "midi_controller"

    def _section_of(self, row) -> Optional[str]:
        """The heading a grid sits under, lowercased.

        Walks back past the column headers: the nearest heading above the firmware
        grid is "Release Notes", which is its own third column rather than a section.
        """
        for element in row.find_all_previous(["h1", "h2", "h3", "h4", "strong"]):
            text = self._clean(element.get_text(" ", strip=True)).lower()
            if text and text not in self.COLUMN_HEADERS and len(text) < 40:
                return text
        return None

    def _parse_grid(self, html: str) -> Dict[str, ScrapedFirmware]:
        """Zip the product column against the version column, row by row."""
        soup = self.parse_html(html)
        found: Dict[str, ScrapedFirmware] = {}

        for row in soup.select("div.row"):
            columns = row.select("div.col")
            if len(columns) < 2:
                continue
            if self._section_of(row) != self.FIRMWARE_SECTION:
                continue

            products = [self._clean(p.get_text(" ", strip=True)) for p in columns[0].select("p")]
            versions = [self._clean(p.get_text(" ", strip=True)) for p in columns[1].select("p")]
            if len(products) != len(versions) or not products:
                # Not the firmware grid, or a layout change that broke the alignment.
                # Guessing which column slipped would be worse than skipping the row.
                continue

            for name, cell in zip(products, versions):
                matched = self.VERSION_AND_DATE.search(cell)
                if not name or not matched:
                    continue
                version, month, day, year = matched.groups()
                try:
                    release_date = datetime(
                        int(year), self.MONTHS[month.lower()], int(day)
                    )
                except (ValueError, KeyError):
                    release_date = None
                found.setdefault(
                    name, ScrapedFirmware(version=version, release_date=release_date)
                )

        return found

    async def _load(self) -> Optional[Dict[str, ScrapedFirmware]]:
        if self._firmware is not None:
            return self._firmware
        html = await self.fetch_page(self.DOWNLOADS_URL)
        if not html:
            return None
        grid = self._parse_grid(html)
        if not grid:
            return None
        self._firmware = grid
        return grid

    async def fetch_device_list(self) -> ScraperResult:
        grid = await self._load()
        if grid is None:
            return ScraperResult(
                success=False, error=f"No firmware grid found at {self.DOWNLOADS_URL}"
            )

        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category=self._category_for(name),
                    firmware_page_url=self.DOWNLOADS_URL,
                    product_url=self.DOWNLOADS_URL,
                )
                for name in sorted(grid)
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        grid = await self._load()
        if grid is None:
            return ScraperResult(
                success=False, error=f"No firmware grid found at {self.DOWNLOADS_URL}"
            )

        firmware = grid.get(device_name)
        if firmware is None:
            # Dropped from the grid. The page loaded, so this is an absence.
            return ScraperResult(success=True, firmware_versions=[])

        # The grid carries only the current release, not a history.
        return ScraperResult(success=True, firmware_versions=[firmware])
