import logging
import re
from datetime import datetime
from typing import List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class DirtywaveScraper(BaseScraper):
    """Dirtywave -- every M8 firmware release, dated, from the firmware repository's change log.

    dirtywave.com's Resources & Downloads page links the M8 firmware from GitHub
    (github.com/Dirtywave/M8Firmware) and its "Changelog on Github". The repository has
    no GitHub releases or tags; the history is ``changelog.txt``, newest first:

        2026-09-13 - Version 6.6.3 C
        - Fix: MIDI intruments CC values always sent on instrument trigger. ...

    One device, the M8: the tracker, M8 Headless and the Model:02 all run this firmware.

    **Suffix letters are releases.** 6.6.3, 6.6.3 A, B and C shipped days apart, and are
    written with and without the space ("6.0.2A"). They are stored without it, as
    dirtywave.com writes "6.6.3C Firmware".

    **The earliest dates are day-first.** 1.0.0 to 1.0.3 read "2020-23-09" and
    "2020-24-10"; a month over 12 is read as the day, which puts them back in order with
    their neighbours. A date that still does not parse is dropped, not guessed.

    **A header can carry a note** -- "2021-05-29 - Version 2.0.0 - Official Production Unit
    Version Support" -- which becomes the first line of that release's notes. 2.7.1 is
    logged twice, word for word; the first entry is kept.
    """

    manufacturer_name = "Dirtywave"
    manufacturer_slug = "dirtywave"
    manufacturer_website = "https://dirtywave.com"

    DEVICE_NAME = "M8"
    CHANGELOG_URL = "https://raw.githubusercontent.com/Dirtywave/M8Firmware/main/changelog.txt"
    PAGE_URL = "https://github.com/Dirtywave/M8Firmware/blob/main/changelog.txt"
    PRODUCT_URL = "https://dirtywave.com/pages/resources-downloads"
    HEADER = re.compile(
        r"^(?P<date>\d{4}-\d{1,2}-\d{1,2})\s*-\s*Version\s+(?P<version>\d+(?:\.\d+)+)"
        r"\s*(?P<suffix>[A-Z])?(?:\s*-\s*(?P<note>.+?))?\s*$"
    )
    NOTES_LIMIT = 4000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._releases: Optional[List[ScrapedFirmware]] = None

    # --- parsing ------------------------------------------------------------

    @staticmethod
    def _parse_date(text: str) -> Optional[datetime]:
        year, first, second = (int(part) for part in text.split("-"))
        month, day = (second, first) if first > 12 else (first, second)
        try:
            return datetime(year, month, day)
        except ValueError:
            return None

    def _parse(self, text: str) -> List[ScrapedFirmware]:
        releases: List[ScrapedFirmware] = []
        notes: List[List[str]] = []
        seen = set()
        current: Optional[List[str]] = None
        for raw in text.splitlines():
            line = raw.strip()
            header = self.HEADER.match(line)
            if header:
                version = header.group("version") + (header.group("suffix") or "")
                if version in seen:
                    current = None
                    continue
                seen.add(version)
                current = [header.group("note")] if header.group("note") else []
                notes.append(current)
                releases.append(ScrapedFirmware(version=version, release_date=self._parse_date(header.group("date"))))
            elif current is not None and line:
                current.append(line)
        for release, lines in zip(releases, notes):
            release.changelog = "\n".join(lines)[: self.NOTES_LIMIT] or None
        return releases

    # --- loading ------------------------------------------------------------

    async def _load(self) -> Optional[List[ScrapedFirmware]]:
        if self._releases is not None:
            return self._releases
        text = await self.fetch_page(self.CHANGELOG_URL)
        self._releases = (self._parse(text) if text else []) or None
        return self._releases

    async def fetch_device_list(self) -> ScraperResult:
        if not await self._load():
            return ScraperResult(success=False, error="M8 firmware change log did not load or listed no version")
        return ScraperResult(success=True, devices=[ScrapedDevice(
            name=self.DEVICE_NAME, category="synthesizer", firmware_page_url=self.PAGE_URL, product_url=self.PRODUCT_URL,
        )])

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        releases = await self._load()
        if not releases:
            return ScraperResult(success=False, error="M8 firmware change log did not load or listed no version")
        return ScraperResult(success=True, firmware_versions=releases if device_name == self.DEVICE_NAME else [])
