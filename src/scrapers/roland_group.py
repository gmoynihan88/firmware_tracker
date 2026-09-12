"""Shared parsing for Roland and Boss, which are the same company and the same site.

Both publish an Updates & Drivers listing per product, and both mix the instrument's
firmware in with things that are not it:

    IR-200 System Program ( Ver.1.10 )              <- the firmware
    IR-200 IR Loader Ver.1.0.0 for Windows          <- a utility
    IR-200 Driver Ver.1.0.1 for macOS Sonoma        <- a USB driver
    Source code of CEF(Chromium Embedded Framework) Version 3.3683.1920  <- a library

A pattern taking the first version on the page can land on any of them. Anchoring on
"System Program" is what separates the firmware from its neighbours.

Neither listing carries a date. The System Program entry links to a detail page that
holds the whole history:

    [ Ver.1.10 ] JAN 2025
    Bug Fixes ...
    [ Ver.1.02 ] MAR 2022

This lives outside plugins/ so the registry does not try to import it as a scraper:
it discovers modules in that package and registers any BaseScraper subclass with a
slug, and a shared mixin is neither.
"""

import re
from datetime import datetime
from typing import List, Optional, Tuple
from urllib.parse import urljoin

from src.scrapers.base import ScrapedFirmware


class SystemProgramMixin:
    """Reads Roland-style System Program listings and their update history."""

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

    def _system_program_link(self, html: str) -> Optional[Tuple[str, str]]:
        """Find the System Program entry, ignoring the drivers beside it."""
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

        Dates are month precision, stored as the first of the month.
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

    async def _fetch_system_program(self, firmware_page_url: str):
        """Listing -> System Program -> detail page. Returns a ScraperResult payload."""
        html = await self.fetch_page(firmware_page_url)
        if not html:
            return None, f"Failed to fetch {firmware_page_url}"

        found = self._system_program_link(html)
        if not found:
            # Products that only ever had drivers. Reporting no firmware is right;
            # reporting a driver version as the instrument's would not be.
            return [], None

        listed_version, detail_url = found
        detail = await self.fetch_page(detail_url)
        if detail:
            history = self._parse_history(detail)
            if history:
                return history, None

        # The detail page exists but had no history block, so keep what the listing
        # stated rather than losing the version entirely.
        return [ScrapedFirmware(version=listed_version)], None
