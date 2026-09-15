"""Shared scraping for Roland and Boss, which are the same company and the same site.

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

**The products come from the Updates & Drivers index** (`/support/updates_drivers/`),
which links every product's listing, A to Z, each as `<h5>MC-101 <small>GROOVEBOX</small></h5>`:
580 on Roland's site and 126 on Boss's on 2026-09-15. The category pages had been
tried first and show only a few featured products each, which is why both scrapers
were a hand-kept list of sixteen. Robots.txt disallows `/support/` at the root and the
regional knowledge bases, not these pages.

About half the index takes firmware -- the rest are drivers-only interfaces, apps and
instruments that never had an update -- and nothing on the index says which, so every
listing is read to find out. That is about 1.4s a product, and the ones with a System
Program cost a second request for the history: a full Roland pass measured 1,945s
on 2026-09-15, and one batch of six 217s. So this follows Korg: the index is sorted by URL and strided into even
batches, the day picks one, and a product outside today's batch reports `not_checked`.
Only products whose listing has a System Program are listed, so the catalogue fills
in over the first cycle and after that every product is re-read once a cycle.

This lives outside plugins/ so the registry does not try to import it as a scraper:
it discovers modules in that package and registers any BaseScraper subclass with a
slug, and a shared mixin is neither.
"""

import logging
import os
import re
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from src.scrapers.base import ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class SystemProgramMixin:
    """Reads Roland-style Updates & Drivers indexes, listings and update history."""

    # Set by each brand.
    INDEX_URL = ""
    BATCHES = 1
    FULL_SWEEP_ENV = ""
    RENAMES: Dict[str, str] = {}

    INDEX_LINK = re.compile(r"/support/by_product/[^/]+/updates_drivers/$")

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

    def __init__(self, *args, full_sweep: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self._catalogue: Optional[Dict[str, dict]] = None
        # The registry constructs scrapers with no arguments, so the environment is
        # the only route for an operator; the argument is for tests and scripts.
        self._full_sweep = full_sweep or os.getenv(self.FULL_SWEEP_ENV or "_", "").strip().lower() in (
            "1", "true", "yes", "on",
        )

    def _category(self, subtitle: str) -> str:
        return "other"

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

    async def _versions_from_listing(self, html: str) -> List[ScrapedFirmware]:
        """Listing -> System Program -> detail page. Empty when there is no firmware."""
        found = self._system_program_link(html)
        if not found:
            # Products that only ever had drivers. Reporting no firmware is right;
            # reporting a driver version as the instrument's would not be.
            return []

        listed_version, detail_url = found
        detail = await self.fetch_page(detail_url)
        if detail:
            history = self._parse_history(detail)
            if history:
                return history

        # The detail page exists but had no history block, so keep what the listing
        # stated rather than losing the version entirely.
        return [ScrapedFirmware(version=listed_version)]

    def _index_products(self, html: str) -> List[Tuple[str, str, str]]:
        """(name, listing URL, subtitle) for every product the index links."""
        products: List[Tuple[str, str, str]] = []
        seen = set()
        for anchor in self.parse_html(html).find_all("a", href=True):
            if not self.INDEX_LINK.search(anchor["href"]):
                continue
            heading = anchor.find("h5")
            if heading is None:
                continue
            small = heading.find("small")
            subtitle = small.get_text(" ", strip=True) if small else ""
            name = " ".join(
                text.strip() for text in heading.find_all(string=True, recursive=False) if text.strip()
            )
            url = urljoin(self.manufacturer_website, anchor["href"])
            if not name or url in seen:
                continue
            seen.add(url)
            products.append((name, url, subtitle))
        return products

    def _today_batch(self) -> int:
        return date.today().toordinal() % self.BATCHES

    def _select_batch(self, products: List[Tuple[str, str, str]]) -> List[Tuple[str, str, str]]:
        """Today's share of the index, or all of it on a full sweep.

        Sorted by URL first so the striding is stable across runs: the index's own
        order is presentation, and a reordering there would otherwise reshuffle every
        batch at once.
        """
        ordered = sorted(products, key=lambda product: product[1])
        if self._full_sweep:
            return ordered
        return ordered[self._today_batch():: self.BATCHES]

    async def _load_catalogue(self) -> Optional[Dict[str, dict]]:
        """Today's products with firmware, each listing and history read once."""
        if self._catalogue is not None:
            return self._catalogue

        index = await self.fetch_page(self.INDEX_URL)
        products = self._index_products(index) if index else []
        if not products:
            return None

        batch = self._select_batch(products)
        logger.info(
            "%s: checking %d of %d products (%s)",
            self.manufacturer_name, len(batch), len(products),
            "full sweep" if self._full_sweep else f"batch {self._today_batch() + 1} of {self.BATCHES}",
        )

        catalogue: Dict[str, dict] = {}
        for name, url, subtitle in batch:
            listing = await self.fetch_page(url)
            if not listing:
                # A listing that fails to load would drop its product from today's
                # catalogue without a word.
                return None
            versions = await self._versions_from_listing(listing)
            if versions:
                catalogue[self.RENAMES.get(name, name)] = {
                    "url": url,
                    "category": self._category(subtitle),
                    "versions": versions,
                }

        self._catalogue = catalogue
        return catalogue

    async def fetch_device_list(self) -> ScraperResult:
        catalogue = await self._load_catalogue()
        if catalogue is None:
            return ScraperResult(
                success=False,
                error=f"Could not read {self.manufacturer_name}'s Updates & Drivers index at {self.INDEX_URL}",
            )
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category=entry["category"],
                    firmware_page_url=entry["url"],
                    product_url=entry["url"].replace("/support/by_product/", "/products/").replace("/updates_drivers/", "/"),
                )
                for name, entry in sorted(catalogue.items())
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        catalogue = await self._load_catalogue()
        if catalogue is None:
            return ScraperResult(
                success=False,
                error=f"Could not read {self.manufacturer_name}'s Updates & Drivers index at {self.INDEX_URL}",
            )

        entry = catalogue.get(device_name)
        if entry is None:
            # Outside today's batch, or no longer offering firmware. Both are "we did
            # not look today", which is what not_checked says; an empty success would
            # claim the product publishes nothing, false most days.
            return ScraperResult(success=True, not_checked=True)
        return ScraperResult(success=True, firmware_versions=entry["versions"])
