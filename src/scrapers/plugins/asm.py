import logging
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional, Tuple

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class ASMScraper(BaseScraper):
    """ASM (Ashun Sound Machines) -- Hydrasynth, Leviasynth and Diosynth firmware, from the download files.

    ashunsoundmachines.com is a Wix site. /downloads links each synth's current firmware
    and /download-legacy the ones before it, all served from mecldata.com:

        <a aria-label="Hydrasynth Explorer Firmware Pack 2.2.0"
           href="https://www.mecldata.com/download/asm/Hydrasynth_Explorer_Firmware_Pack_2.2.0.zip">

    **The file name is the release.** Product and version are read from it --
    "Hydrasynth_Deluxe_Firmware_Pack_2.2.0.zip", "Diosynth_Firmware_1.1.4.dat" -- so the
    ASM Manager and Hydrasynth Updater apps, owner's manuals ("Owner's Manual 2.2.0") and
    "Hydrasynth_KB_DR_Update_Notes_1.5.4.pdf" beside them are not.

    **The downloads page holds two copies of its list**, one per Wix layout, and they
    disagree: one links Leviasynth Firmware Pack 1.2.0, the other still 1.1.1. Both are
    read, versions are merged per product with the legacy page's, and the newest comes
    first.

    **Dates come from the blog, where a post names the firmware.** /blog-feed.xml has "new
    2.2 firmware for all Hydrasynth models" (2025-05-15) and "Leviasynth firmware v1.2 is
    now available" (2026-07-24). A post dates the version it names -- 2.2 is 2.2.0 -- on
    every product of that family. The rest of the history is undated; the feed only
    reaches back to 2023, and the legacy files carry no dates. If the feed fails, the
    releases are stored undated.
    """

    manufacturer_name = "ASM"
    manufacturer_slug = "asm"
    manufacturer_website = "https://www.ashunsoundmachines.com"

    BASE_URL = "https://www.ashunsoundmachines.com"
    DOWNLOADS_URL = BASE_URL + "/downloads"
    LEGACY_URL = BASE_URL + "/download-legacy"
    FEED_URL = BASE_URL + "/blog-feed.xml"

    FIRMWARE_FILE = re.compile(
        r"/(?P<name>[A-Za-z0-9]+(?:_[A-Za-z0-9]+)*?)_Firmware(?:_Pack)?_(?P<version>\d+(?:\.\d+)+)\.(?:zip|dat)$"
    )
    FEED_ITEM = re.compile(r"<item>(?P<item>.*?)</item>", re.S)
    FEED_TITLE = re.compile(r"<title>(?:<!\[CDATA\[)?(?P<title>.*?)(?:\]\]>)?</title>", re.S)
    FEED_DATE = re.compile(r"<pubDate>(?P<date>.*?)</pubDate>", re.S)
    POST_FAMILY = re.compile(r"\b(?P<family>Hydrasynth|Leviasynth|Diosynth)\b", re.I)
    POST_VERSION = re.compile(
        r"\bv?(?P<before>\d+(?:\.\d+)+)\s+firmware\b|\bfirmware\s+v?(?P<after>\d+(?:\.\d+)+)\b", re.I
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._devices: Optional[Dict[str, List[ScrapedFirmware]]] = None

    # --- parsing ------------------------------------------------------------

    @staticmethod
    def _version_key(version: str) -> Tuple[int, ...]:
        parts = [int(part) for part in version.split(".")]
        while len(parts) > 1 and parts[-1] == 0:
            parts.pop()
        return tuple(parts)

    def _parse_files(self, html: str) -> Dict[str, List[str]]:
        """Product -> versions linked, in page order."""
        found: Dict[str, List[str]] = {}
        for link in self.parse_html(html).find_all("a", href=True):
            matched = self.FIRMWARE_FILE.search(link["href"].split("?")[0])
            if matched:
                versions = found.setdefault(matched.group("name").replace("_", " "), [])
                if matched.group("version") not in versions:
                    versions.append(matched.group("version"))
        return found

    def _parse_feed(self, xml: str) -> Dict[Tuple[str, Tuple[int, ...]], datetime]:
        """(family, version key) -> the date of the post announcing that firmware."""
        dates: Dict[Tuple[str, Tuple[int, ...]], datetime] = {}
        for item in self.FEED_ITEM.finditer(xml):
            title = self.FEED_TITLE.search(item.group("item"))
            published = self.FEED_DATE.search(item.group("item"))
            if not title or not published:
                continue
            family = self.POST_FAMILY.search(title.group("title"))
            version = self.POST_VERSION.search(title.group("title"))
            if not family or not version:
                continue
            try:
                date = parsedate_to_datetime(published.group("date").strip())
            except (TypeError, ValueError):
                continue
            key = (family.group("family").title(), self._version_key(version.group("before") or version.group("after")))
            dates.setdefault(key, datetime(date.year, date.month, date.day))
        return dates

    # --- loading ------------------------------------------------------------

    async def _load(self) -> Optional[Dict[str, List[ScrapedFirmware]]]:
        if self._devices is not None:
            return self._devices
        current = await self.fetch_page(self.DOWNLOADS_URL)
        files = self._parse_files(current) if current else {}
        if not files:
            return None
        legacy = await self.fetch_page(self.LEGACY_URL)
        if not legacy:
            logger.warning("ASM legacy downloads did not load; current firmware only")
        for name, versions in (self._parse_files(legacy) if legacy else {}).items():
            if name in files:
                files[name].extend(v for v in versions if v not in files[name])
        feed = await self.fetch_page(self.FEED_URL)
        dates = self._parse_feed(feed) if feed else {}
        devices: Dict[str, List[ScrapedFirmware]] = {}
        for name, versions in files.items():
            family = name.split()[0].title()
            devices[name] = [
                ScrapedFirmware(version=version, release_date=dates.get((family, self._version_key(version))))
                for version in sorted(versions, key=lambda v: tuple(int(p) for p in v.split(".")), reverse=True)
            ]
        self._devices = devices
        return devices

    async def fetch_device_list(self) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error="ASM downloads page linked no firmware")
        return ScraperResult(
            success=True,
            devices=[ScrapedDevice(name=name, category="synthesizer", firmware_page_url=self.DOWNLOADS_URL,
                                   product_url=self.DOWNLOADS_URL) for name in devices],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error="ASM downloads page linked no firmware")
        return ScraperResult(success=True, firmware_versions=devices.get(device_name, []))
