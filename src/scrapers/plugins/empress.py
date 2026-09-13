import re
from datetime import datetime
from typing import Dict, List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class EmpressEffectsScraper(BaseScraper):
    """Empress Effects, read from its two firmware pages.

    Four products, and the versions are split across two pages that have to be read
    together:

        /pages/firmware-updates        Echosystem   Download Firmware (v2.50)
        /pages/old-firmware-downloads  Echosystem   Firmware v2.42 — Released 2025-11-14

    The current release is on the first page with no date; every earlier one is on
    the archive with a date. Reading only the first gives four undated versions and
    no history; reading only the archive reports v2.42 as current, eight releases
    behind. 99 versions in total, 95 of them dated.

    Both pages are JavaScript-rendered -- a plain fetch returns about 1,400
    characters of shell with the firmware section missing entirely, which reads
    exactly like a vendor that publishes nothing.

    The markup is unusually helpful: `div.firmware-product` and
    `div.old-firmware-product` per product, `a.firmware-product__button` holding the
    current version, and `li.old-firmware-product__item` holding one historical
    release each. Both pages spell the product names the same way, so no alias map
    is needed.

    **ZOIA and ZOIA Euroburo share a firmware line.** Both report v5.41 and the same
    28 historical releases, because one build serves both, the way UAFX versions the
    platform rather than each pedal. Two products out of four sharing a version is
    below `audit_scrapers.py`'s threshold, so it will not be flagged, but it is not a
    bug if it ever is.

    The current version carries no date because the page states none. Inventing one
    from the archive's newest entry would attach v2.42's release date to v2.50.
    """

    manufacturer_name = "Empress Effects"
    manufacturer_slug = "empress"
    manufacturer_website = "https://empresseffects.com"

    CURRENT_URL = "https://empresseffects.com/pages/firmware-updates"
    ARCHIVE_URL = "https://empresseffects.com/pages/old-firmware-downloads"

    # "Download Firmware (v2.50)"
    CURRENT_VERSION = re.compile(r"\(v\s*(\d+(?:\.\d+)+)\s*\)", re.I)
    # "Firmware v2.42 — Released 2025-11-14"
    ARCHIVE_ENTRY = re.compile(
        r"Firmware\s+v\s*(\d+(?:\.\d+)+)\b(?:.*?Released\s+(\d{4})-(\d{2})-(\d{2}))?",
        re.I | re.S,
    )

    RENDER_WAIT = 15000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._firmware: Optional[Dict[str, List[ScrapedFirmware]]] = None

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(part) for part in re.findall(r"\d+", version)) or (0,)

    @staticmethod
    def _product_name(block) -> Optional[str]:
        heading = block.find(["h1", "h2", "h3", "h4"])
        if heading is None:
            return None
        name = " ".join(heading.get_text(" ", strip=True).split())
        return name or None

    def _parse_current(self, html: str) -> Dict[str, ScrapedFirmware]:
        """The shipping version for each product, which the page does not date."""
        soup = self.parse_html(html)
        found: Dict[str, ScrapedFirmware] = {}

        for block in soup.select("div.firmware-product"):
            name = self._product_name(block)
            button = block.select_one("a.firmware-product__button")
            if not name or button is None:
                continue
            matched = self.CURRENT_VERSION.search(button.get_text(" ", strip=True))
            if not matched:
                continue
            found[name] = ScrapedFirmware(version=matched.group(1), release_date=None)

        return found

    def _parse_archive(self, html: str) -> Dict[str, List[ScrapedFirmware]]:
        """Every earlier release, each with the date the archive states."""
        soup = self.parse_html(html)
        found: Dict[str, List[ScrapedFirmware]] = {}

        for block in soup.select("div.old-firmware-product"):
            name = self._product_name(block)
            if not name:
                continue
            versions: List[ScrapedFirmware] = []
            for item in block.select("li.old-firmware-product__item"):
                matched = self.ARCHIVE_ENTRY.search(item.get_text(" ", strip=True))
                if not matched:
                    continue
                version, year, month, day = matched.groups()
                release_date = None
                if year:
                    try:
                        release_date = datetime(int(year), int(month), int(day))
                    except ValueError:
                        release_date = None
                versions.append(
                    ScrapedFirmware(version=version, release_date=release_date)
                )
            if versions:
                found[name] = versions

        return found

    async def _load(self) -> Optional[Dict[str, List[ScrapedFirmware]]]:
        if self._firmware is not None:
            return self._firmware

        current_html = await self.fetch_page_js(
            self.CURRENT_URL, wait_for_timeout=self.RENDER_WAIT
        )
        if not current_html:
            return None
        current = self._parse_current(current_html)
        if not current:
            return None

        archive_html = await self.fetch_page_js(
            self.ARCHIVE_URL, wait_for_timeout=self.RENDER_WAIT
        )
        # The archive is history rather than the answer to "am I behind", so a
        # failure there costs dates and old versions, not the current release.
        archive = self._parse_archive(archive_html) if archive_html else {}

        merged: Dict[str, List[ScrapedFirmware]] = {}
        for name, shipping in current.items():
            seen = {shipping.version}
            versions = [shipping]
            for older in archive.get(name, []):
                if older.version in seen:
                    continue
                seen.add(older.version)
                versions.append(older)
            merged[name] = sorted(
                versions, key=lambda fw: self._version_key(fw.version), reverse=True
            )

        self._firmware = merged
        return merged

    async def fetch_device_list(self) -> ScraperResult:
        firmware = await self._load()
        if firmware is None:
            return ScraperResult(
                success=False, error=f"No firmware entries found at {self.CURRENT_URL}"
            )

        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category="guitar_pedal",
                    firmware_page_url=self.CURRENT_URL,
                    product_url=self.CURRENT_URL,
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
                success=False, error=f"No firmware entries found at {self.CURRENT_URL}"
            )

        versions = firmware.get(device_name)
        if versions is None:
            # Dropped from the page. It rendered, so this is an absence.
            return ScraperResult(success=True, firmware_versions=[])

        return ScraperResult(success=True, firmware_versions=versions)
