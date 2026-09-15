import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)

MONTHS = {name: number for number, name in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


class CockosScraper(BaseScraper):
    """Cockos REAPER, from the changelog it has kept since 2005.

    `reaper.fm/whatsnew.txt` is one plain-text file, newest first, with every
    release back to v0.41 in December 2005 -- over 700 of them, each dated:

        v7.80 - September 13 2026
          + Actions: reset JSFX loudness meters on monitoring FX...
          + CLAP: support CLAP_EVENT_IS_LIVE

    **The file is not UTF-8.** It is Windows-1252, 1.4MB, and a strict UTF-8 decode
    fails at byte 1,275,402 -- which lost the whole file, not just that character.
    `netguard.read_text_capped` now falls back to cp1252 for undeclared text.

    **Only full releases are read.** The file also carries every pre-release --
    "v4.0rc5", "v2.0b16", "v1.0b6" -- whose version is followed by more than a single
    letter. A single trailing letter is a real release: 6.12c shipped in June 2020.

    **An entry runs until the next version heading**, not until the next unindented
    line. 4.0's notes open with "4.0 headline changes:" at the margin, and stopping
    there left the biggest release in the file with no notes.

    **Month names are misspelled**: "Feburary 1 2025", "Februrary 21 2020",
    "Feburary 24 2017". A month is read by its first three letters; strict month
    names left those three releases undated.

    Two dates are not what they seem:

    - "v2.013 - November 27ish 2007" is the vendor's own approximation. The version
      is kept and left undated rather than stamped with a day it does not claim.
    - 4.21 appears twice, dated 2012-03-23 and 2012-04-05. It is one version, dated by
      its first release, with both sets of notes.

    One device, "REAPER": every build of it is the same product on every platform.
    """

    manufacturer_name = "Cockos"
    manufacturer_slug = "cockos"
    manufacturer_website = "https://www.reaper.fm"

    CHANGELOG_URL = "https://www.reaper.fm/whatsnew.txt"
    PRODUCT_URL = "https://www.reaper.fm/download.php"
    PRODUCT_NAME = "REAPER"

    # "v7.80 - September 13 2026", "v0.41 - Dec 26 2005", "v6.12c - June 15 2020".
    RELEASE = re.compile(
        r"^v?(?P<version>\d+\.\d+(?:\.\d+)*[a-z]?)\s+-\s+"
        r"(?P<month>[A-Za-z]+)\.?\s+(?P<day>\d{1,2})(?P<approx>ish)?,?\s+(?P<year>\d{4})\s*:?\s*$"
    )
    # Anything shaped like a version heading, pre-releases included, ends an entry.
    ANY_HEADING = re.compile(r"^v?\.?\d[\w.]*\s+-\s+\S")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._versions: Optional[List[ScrapedFirmware]] = None

    @staticmethod
    def _date(month: str, day: str, year: str) -> Optional[datetime]:
        """By the month's first three letters: the log spells February "Feburary" twice
        and "Februrary" once, and it also abbreviates ("Dec 26 2005")."""
        number = MONTHS.get(month[:3].lower())
        if number is None:
            return None
        try:
            return datetime(int(year), number, int(day))
        except ValueError:
            return None

    def _parse_changelog(self, text: str) -> List[ScrapedFirmware]:
        entries: List[Tuple[Optional[str], Optional[datetime], List[str]]] = []
        for line in text.splitlines():
            stripped = line.strip()
            if line and not line[0].isspace() and self.ANY_HEADING.match(stripped):
                release = self.RELEASE.match(stripped)
                if release is None:
                    # A pre-release: its notes belong to nothing we record.
                    entries.append((None, None, []))
                    continue
                released = None if release.group("approx") else self._date(
                    release.group("month"), release.group("day"), release.group("year")
                )
                entries.append((release.group("version"), released, []))
                continue
            if entries and stripped:
                entries[-1][2].append(stripped)

        versions: Dict[str, ScrapedFirmware] = {}
        for version, released, notes in entries:
            if version is None:
                continue
            changelog = "\n".join(notes) or None
            existing = versions.get(version)
            if existing is None:
                versions[version] = ScrapedFirmware(version=version, release_date=released, changelog=changelog)
                continue
            # Newest first, so a version repeated further down is its first release.
            if released and (existing.release_date is None or released < existing.release_date):
                existing.release_date = released
            if changelog:
                existing.changelog = "\n".join(filter(None, [existing.changelog, changelog]))
        # The file's own order: REAPER's early numbering (2.013 before 2.02) does not sort.
        return list(versions.values())

    async def _load(self) -> Optional[List[ScrapedFirmware]]:
        if self._versions is None:
            text = await self.fetch_page(self.CHANGELOG_URL)
            versions = self._parse_changelog(text) if text else []
            self._versions = versions or None
        return self._versions

    async def fetch_device_list(self) -> ScraperResult:
        if await self._load() is None:
            return ScraperResult(success=False, error=f"No releases found in {self.CHANGELOG_URL}")
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=self.PRODUCT_NAME,
                    category="vst_plugin",
                    firmware_page_url=self.CHANGELOG_URL,
                    product_url=self.PRODUCT_URL,
                )
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        versions = await self._load()
        if versions is None:
            return ScraperResult(success=False, error=f"No releases found in {self.CHANGELOG_URL}")
        if device_name != self.PRODUCT_NAME:
            return ScraperResult(success=True, firmware_versions=[])
        return ScraperResult(success=True, firmware_versions=list(versions))
