import re
from typing import Dict, List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class ZoomScraper(BaseScraper):
    """Zoom Corporation, read from the one firmware page that covers the range.

    Seventeen products on a single page, each an anchor to the firmware archive
    itself. **The version is in the filename, and the filename is the source of
    truth**, because the link text goes stale:

        F6 Firmware 2.00 + Audio Driver   ->  /documents/.../F6_v2.20E.zip
        R20 System Version 3.30           ->  /documents/.../R20_v3.40_E.zip

    Two products currently advertise a version one release behind what they
    actually ship. Reading the title would report both as stale forever, and
    reading it only when the filename has no number keeps the honest fallback
    without preferring the wrong one.

    **Zoom writes the link two ways**, and a filter fitted to one drops the
    other silently:

        H2n Firmware                 the common form
        R20 System Version 3.30      recorders with a "system"

    Requiring the word "Firmware" alone looked like a clean seventeen-product
    read and was quietly missing three.

    Three traps on the same page:

    - **Accessibility files are versioned and are not firmware.** "H1essential
      Accessibility File ... Guide Sound Version 1.00" matches "System Version"
      closely enough to slip through, and would report 1.00 against a product
      whose firmware is elsewhere.
    - **One product, two platform builds.** MS-90LP+, AC-2 and B1X Four each
      publish a Windows and a macOS updater carrying the same firmware, so the
      name is the key and the highest version wins.
    - **A trailing uppercase `E` is a language marker**, not a revision:
      `H2n_v3.00E.zip` is 3.00. A *lowercase* suffix is real -- `H6_v2.50a_E.zip`
      is 2.50a, and stripping it would merge two distinct releases.

    **No dates.** The page states none, and the only version histories Zoom
    publishes are three PDFs (Q2n-4K and two AMS-22 components), so there is no
    date to recover for the other fourteen products. Versions are stored undated
    rather than stamped with the date the page was read.

    Only the current release is published; there is no history page.
    """

    manufacturer_name = "Zoom"
    manufacturer_slug = "zoom"
    manufacturer_website = "https://zoomcorp.com"

    FIRMWARE_URL = "https://zoomcorp.com/en/us/support/firmware/"

    # Both wordings Zoom uses for a firmware download.
    WANTED = re.compile(r"\b(?:firmware|system version)\b", re.I)
    # Entries that match the wording above and are not the product's firmware.
    NOT_FIRMWARE = re.compile(r"accessibility|guide sound|driver only|manual", re.I)

    # "H2n_v3.00E.zip", "H6_v2.50a_E.zip", "P4_v1.40_E.zip"
    FILENAME_VERSION = re.compile(r"_v?(\d+(?:\.\d+)+[a-z]?)", re.I)
    # "R20 System Version 3.30" -- used only when the filename carries no version.
    TITLE_VERSION = re.compile(r"(\d+(?:\.\d+)+[a-z]?)\s*$")
    # Parenthesised file sizes read as versions: "Firmware ReadMe (76.74 kB)".
    FILE_SIZE = re.compile(r"\([^)]*\b[kmg]b\b[^)]*\)", re.I)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._firmware: Optional[Dict[str, ScrapedFirmware]] = None
        self._urls: Dict[str, str] = {}

    @staticmethod
    def _version_key(version: str) -> tuple:
        """2.50a sorts above 2.50; the letter is a revision of the same release."""
        numbers = tuple(int(part) for part in re.findall(r"\d+", version))
        suffix = re.search(r"[a-z]$", version, re.I)
        return numbers, suffix.group(0).lower() if suffix else ""

    @classmethod
    def _strip_language(cls, version: str) -> str:
        """H2n_v3.00E -> 3.00, while H6_v2.50a keeps its 'a'."""
        return re.sub(r"E$", "", version)

    @classmethod
    def _product_name(cls, title: str) -> str:
        return re.split(r"\s+(?:firmware|system version)\b", title, flags=re.I)[0].strip()

    def _parse(self, html: str) -> Dict[str, ScrapedFirmware]:
        soup = self.parse_html(html)
        found: Dict[str, ScrapedFirmware] = {}

        for anchor in soup.find_all("a", href=True):
            title = self.FILE_SIZE.sub("", anchor.get_text(" ", strip=True)).strip()
            if not self.WANTED.search(title) or self.NOT_FIRMWARE.search(title):
                continue

            href = anchor["href"]
            filename = href.rstrip("/").rsplit("/", 1)[-1]
            matched = self.FILENAME_VERSION.search(filename)
            if matched:
                version = self._strip_language(matched.group(1))
            else:
                # No number in the filename -- the title is all there is.
                by_title = self.TITLE_VERSION.search(title)
                if not by_title:
                    continue
                version = by_title.group(1)

            name = self._product_name(title)
            if not name:
                continue

            # Windows and macOS updaters for one product, and the occasional
            # superseded entry left on the page.
            existing = found.get(name)
            if existing is not None and self._version_key(
                existing.version
            ) >= self._version_key(version):
                continue

            found[name] = ScrapedFirmware(version=version)
            self._urls[name] = self.FIRMWARE_URL

        return found

    async def _load(self) -> Optional[Dict[str, ScrapedFirmware]]:
        if self._firmware is not None:
            return self._firmware
        html = await self.fetch_page(self.FIRMWARE_URL)
        if not html:
            return None
        firmware = self._parse(html)
        if not firmware:
            return None
        self._firmware = firmware
        return firmware

    # UAC-8 is an interface; the pedals are pedals; everything else Zoom makes on
    # this page records something.
    AUDIO_INTERFACE_PREFIXES = ("UAC-",)
    PEDAL_PREFIXES = ("AC-", "B1", "G1", "MS-")

    @classmethod
    def _category_for(cls, name: str) -> str:
        if name.startswith(cls.AUDIO_INTERFACE_PREFIXES):
            return "audio_interface"
        if name.startswith(cls.PEDAL_PREFIXES):
            return "guitar_pedal"
        return "other"

    async def fetch_device_list(self) -> ScraperResult:
        firmware = await self._load()
        if firmware is None:
            return ScraperResult(
                success=False, error=f"No firmware entries found at {self.FIRMWARE_URL}"
            )

        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category=self._category_for(name),
                    firmware_page_url=self.FIRMWARE_URL,
                    product_url=self.FIRMWARE_URL,
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
                success=False, error=f"No firmware entries found at {self.FIRMWARE_URL}"
            )

        version = firmware.get(device_name)
        if version is None:
            # Dropped from the page. It loaded, so this is an absence.
            return ScraperResult(success=True, firmware_versions=[])
        return ScraperResult(success=True, firmware_versions=[version])
