import re
from datetime import datetime
from typing import Dict, List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class FractalAudioScraper(BaseScraper):
    """Fractal Audio, read from the per-product downloads pages its homepage links.

    Eight products, one current firmware each, five of them dated. Each page is an
    iconbox list whose firmware entry states the version in its title and the date in
    the line below:

        <h3 class="w-iconbox-title">Firmware 32.06</h3>
        Compatible with all Axe-Fx III models and versions – June 25, 2026

    Product pages are discovered from the homepage rather than transcribed: it links
    `/<slug>-downloads/` for every product, so one Fractal discontinues or adds is
    picked up without an edit here.

    **Fractal writes the firmware title three ways**, and a pattern fitted to one of
    them silently drops the others. All three are real, on pages that otherwise look
    identical:

        Firmware 32.06                    Axe-Fx III, FX8, MFC
        Firmware v12.0                    FM9, FM3, VP4
        AX8 Firmware Quantum 10.01        AX8

    So the version is taken as the trailing number of any iconbox title containing
    the word Firmware, whatever precedes it. That is deliberately loose, and the one
    thing it must refuse is `USB Firmware Update 1.04` -- a separate chip's firmware
    that sits in the same list on the FM9 page, so "USB" anywhere in the title
    disqualifies it.

    These pages carry several other numbers that a looser reading collects: preset
    bank versions ("compatible with firmware 28.06 or newer"), the Axe-Edit editor
    ("Executable – June 10, 2026 – Version 6.16") and a USB driver ("driver version
    5.12"). Reading only the iconbox titles keeps all of them out.

    Only the current release is published per product; there is no history page.

    **Only products whose firmware could be read are listed.** Axe-Fx II is linked
    from the homepage and states its firmware in a shape none of the three patterns
    match. Listing it anyway would add a row that reports nothing on every run --
    the Focusrite failure, self-inflicted on one product -- so the device list fetches
    each page once and keeps what it finds. Nine fetches, about a second, and
    `fetch_firmware_versions` then costs nothing.
    """

    manufacturer_name = "Fractal Audio"
    manufacturer_slug = "fractal"
    manufacturer_website = "https://www.fractalaudio.com"

    # Slug -> display name. Fractal's own spelling; the slug alone gives "Fm9".
    NAMES = {
        "axe-fx-iii": "Axe-Fx III",
        "axe-fx-ii": "Axe-Fx II",
        "fm9": "FM9",
        "fm3": "FM3",
        "vp4": "VP4",
        "am4": "AM4",
        "ax8": "AX8",
        "fx8": "FX8",
        "mfc": "MFC-101",
    }

    # Any iconbox title naming firmware, excluding the USB chip's own updater.
    FIRMWARE_TITLE = re.compile(
        r"^(?!.*\bUSB\b).*?\bFirmware\b[^\d]*?(\d+(?:\.\d+)+)\s*$", re.I
    )
    RELEASE_DATE = re.compile(
        r"(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+(\d{1,2}),\s+(\d{4})"
    )
    MONTHS = {month: index for index, month in enumerate(
        ["january", "february", "march", "april", "may", "june", "july",
         "august", "september", "october", "november", "december"], start=1)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._products: Optional[Dict[str, str]] = None
        self._firmware: Optional[Dict[str, List[ScrapedFirmware]]] = None
        self._urls: Dict[str, str] = {}

    def _display_name(self, slug: str) -> str:
        if slug in self.NAMES:
            return self.NAMES[slug]
        return "-".join(part.upper() if len(part) <= 3 else part.capitalize()
                        for part in slug.split("-"))

    async def _discover(self) -> Optional[Dict[str, str]]:
        """name -> downloads URL, from the links on the homepage."""
        if self._products is not None:
            return self._products

        html = await self.fetch_page(self.manufacturer_website + "/")
        if not html:
            return None

        soup = self.parse_html(html)
        found: Dict[str, str] = {}
        for anchor in soup.find_all("a", href=True):
            match = re.search(r"/([a-z0-9-]+)-downloads/?$", anchor["href"])
            if not match:
                continue
            slug = match.group(1)
            found.setdefault(
                self._display_name(slug),
                f"{self.manufacturer_website}/{slug}-downloads/",
            )

        if not found:
            return None
        self._products = found
        return found

    def _parse_product(self, html: str) -> List[ScrapedFirmware]:
        soup = self.parse_html(html)
        for title in soup.select("h3.w-iconbox-title"):
            matched = self.FIRMWARE_TITLE.match(title.get_text(" ", strip=True))
            if not matched:
                continue

            release_date = None
            box = title.find_parent("div", class_="w-iconbox")
            if box is not None:
                dated = self.RELEASE_DATE.search(box.get_text(" ", strip=True))
                if dated:
                    month, day, year = dated.groups()
                    try:
                        release_date = datetime(
                            int(year), self.MONTHS[month.lower()], int(day)
                        )
                    except (ValueError, KeyError):
                        release_date = None

            return [ScrapedFirmware(version=matched.group(1), release_date=release_date)]

        return []

    async def _load(self) -> Optional[Dict[str, List[ScrapedFirmware]]]:
        if self._firmware is not None:
            return self._firmware

        products = await self._discover()
        if products is None:
            return None

        firmware: Dict[str, List[ScrapedFirmware]] = {}
        for name, url in products.items():
            html = await self.fetch_page(url)
            if not html:
                continue
            versions = self._parse_product(html)
            if versions:
                firmware[name] = versions
            self._urls[name] = url

        if not firmware:
            return None
        self._firmware = firmware
        return firmware

    async def fetch_device_list(self) -> ScraperResult:
        firmware = await self._load()
        if firmware is None:
            return ScraperResult(
                success=False,
                error=f"No firmware found on the pages linked from {self.manufacturer_website}",
            )

        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category="guitar_pedal",
                    firmware_page_url=self._urls[name],
                    product_url=self._urls[name],
                )
                for name in sorted(firmware)
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        firmware = await self._load()
        if firmware is None:
            return ScraperResult(
                success=False,
                error=f"No firmware found on the pages linked from {self.manufacturer_website}",
            )

        versions = firmware.get(device_name)
        if versions is None:
            # Fractal has dropped the product, or its page changed shape. The
            # homepage loaded, so this is an absence rather than a break.
            return ScraperResult(success=True, firmware_versions=[])
        return ScraperResult(success=True, firmware_versions=versions)
