import logging
import re
from datetime import datetime
from typing import List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)

MONTHS = {name: number for number, name in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


class AvidScraper(BaseScraper):
    """Avid Pro Tools, from the "What's new in Pro Tools" page.

    One page lists each Pro Tools release since 2023.3 under its own heading, with
    the month it shipped in brackets and the features below:

        <h2>PRO TOOLS 2026.4.1 (JULY 2026)</h2>
        <h2>PRO TOOLS 2026.4 (APRIL 2026)</h2>
          <h3>Faster editing and navigation with Track Pin</h3> <p>...</p>

    **Only Pro Tools releases are read.** The same list carries third-party
    announcements -- "FORTE FOR PRO TOOLS (JUNE 2025)", "K-Devices TATAT MIDI Plugin
    (April 2025)", "ACON DIGITAL ACOUSTICA ARA SUPPORT (DECEMBER 2024)" -- so a heading
    must begin "PRO TOOLS" and be followed by a version.

    **The date is the heading's month, not the version's.** Avid versions name a year
    and month -- 2026.4 is April 2026 -- but a point release patches that version later:
    2026.4.1 shipped in July. The day is never published, so a release is stored on
    the first of its month, the way Roland's month-only dates are.

    The page starts at 2023.3; older releases each have a resource-center page with
    no date at all, and are not read.

    One device, "Pro Tools", with the other desktop software.
    """

    manufacturer_name = "Avid"
    manufacturer_slug = "avid"
    manufacturer_website = "https://www.avid.com"

    WHATS_NEW_URL = "https://www.avid.com/pro-tools/whats-new"
    PRODUCT_NAME = "Pro Tools"

    RELEASE = re.compile(
        r"^PRO\s+TOOLS\s+(?P<version>\d{4}\.\d{1,2}(?:\.\d+)*)\s*\((?P<month>[A-Za-z]+)\s+(?P<year>\d{4})\)\s*$",
        re.I,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._versions: Optional[List[ScrapedFirmware]] = None

    def _parse_whats_new(self, html: str) -> List[ScrapedFirmware]:
        soup = self.parse_html(html)
        versions: List[ScrapedFirmware] = []
        seen = set()
        for heading in soup.find_all("h2"):
            matched = self.RELEASE.match(" ".join(heading.get_text(" ").split()))
            if not matched or matched.group("version") in seen:
                continue
            seen.add(matched.group("version"))
            month = MONTHS.get(matched.group("month")[:3].lower())
            released = datetime(int(matched.group("year")), month, 1) if month else None

            versions.append(ScrapedFirmware(
                version=matched.group("version"),
                release_date=released,
                changelog="\n".join(self._notes(heading)) or None,
            ))
        return versions

    @staticmethod
    def _notes(heading) -> List[str]:
        """The text between a heading and the next one.

        Each heading sits alone in a wrapper div, its notes in the div after that, so
        climb to the outermost element the heading ends, then read the blocks that
        follow it until one holds another heading.
        """
        block = heading
        while block.parent is not None and block.parent.name != "body" and block.find_next_sibling() is None:
            block = block.parent

        notes: List[str] = []
        for sibling in block.find_next_siblings():
            if sibling.name == "h2" or sibling.find("h2"):
                break
            for part in sibling.find_all(["h3", "p", "li"]) or [sibling]:
                if part.name == "p" and part.find_parent("li"):
                    continue
                text = " ".join(part.get_text(" ").split())
                if text:
                    notes.append(text)
        return notes

    async def _load(self) -> Optional[List[ScrapedFirmware]]:
        if self._versions is None:
            html = await self.fetch_page(self.WHATS_NEW_URL)
            versions = self._parse_whats_new(html) if html else []
            self._versions = versions or None
        return self._versions

    async def fetch_device_list(self) -> ScraperResult:
        if await self._load() is None:
            return ScraperResult(success=False, error=f"No Pro Tools releases found at {self.WHATS_NEW_URL}")
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=self.PRODUCT_NAME,
                    category="vst_plugin",
                    firmware_page_url=self.WHATS_NEW_URL,
                    product_url=self.WHATS_NEW_URL,
                )
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        versions = await self._load()
        if versions is None:
            return ScraperResult(success=False, error=f"No Pro Tools releases found at {self.WHATS_NEW_URL}")
        if device_name != self.PRODUCT_NAME:
            return ScraperResult(success=True, firmware_versions=[])
        return ScraperResult(success=True, firmware_versions=list(versions))
