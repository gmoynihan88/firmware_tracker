import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)

MONTHS = {name: number for number, name in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


class ImageLineScraper(BaseScraper):
    """Image-Line FL Studio, from the What's New page of its online manual.

    One page lists every build back to FruityLoops 1.2 in 1998, each under its own
    heading -- h2 for some eras, h3 for others -- with the date in brackets and the
    notes below:

        <h3>26.1.6 (2026/09/02)</h3>

    Maintained by hand for 28 years, and it shows.

    **Pre-releases are mixed in** and skipped: "26.1 RC1", "26.1 beta 11",
    "21.0.99 Beta 2", "12.3.1 Release Candidate 1", once "Rlease Candidate", and
    "1.2.13 (not released)".

    **Headings carry words after the version** that do not make it something else:
    "12.4.2 build 33", "11.1 x64", "20.8.3 Initial Release", "20.9.2 macOS bug fix
    update", "20.7.1 macOS update". Where a heading names two versions
    ("20.9.1 20.9.2") only the first is its version.

    **FL Studio 2024 writes its releases with the year**: "2024.2.2", "2024.1.1b". They
    are 24.2.2 and 24.1.1b -- the page itself says so, heading the betas that followed
    "24.2.99 Beta 9", the same form as "21.0.99 Beta" before 21.1. Stored as written,
    2024.2.2 would sort above 26.1.6 and become the latest version.

    **The date is written every way a date can be**:

        (2026/09/02)            year / month / day
        (2023 / Aug / 29)       year / month name / day
        (03 / Apr / 2017)       day / month name / year
        (9 December 2019)       no separators
        (22 / Feb / ruary 2019) a month split in two
        (21 / March / 98 )      a two-digit year: 1998
        (4 December 2018) )    a stray bracket after it

    so the brackets are read as tokens -- a month name by its first three letters, a
    four-digit year wherever it sits -- rather than against one pattern.

    **Repeated versions** (11.5.13, 12.3.1, 12.5.1, 20.0.5 each appear twice, a build
    re-released) are one version, dated by their first release.

    One device, "FL Studio": the download page's build numbers differ by platform
    (26.1.6.5639 on Windows, 26.1.6.5406 on macOS), and the manual's version is the
    one both share.
    """

    manufacturer_name = "Image-Line"
    manufacturer_slug = "imageline"
    manufacturer_website = "https://www.image-line.com"

    WHATS_NEW_URL = "https://www.image-line.com/fl-studio-learning/fl-studio-online-manual/html/WhatsNew.htm"
    PRODUCT_URL = "https://www.image-line.com/fl-studio-download/"
    PRODUCT_NAME = "FL Studio"

    HEADING = re.compile(
        r"^(?:FL\s+Studio\s+)?(?P<version>\d+(?:\.\d+)+[a-z]?)(?P<rest>[^(]*)(?:\((?P<date>[^)]*)\)?)?(?P<tail>.*)$",
        re.I,
    )
    PRERELEASE = re.compile(
        r"\b(?:beta|alpha|preview|r?e?lease\s+candidate|rlease\s+candidate|not\s+released)\b|\brc\s*\d*\b",
        re.I,
    )
    # Words that may follow a release's version without making it a different thing.
    QUALIFIER = re.compile(
        r"^(?:build\s+\d+|x64|x86|initial\s+release|(?:macos\s+)?(?:bug\s*fix\s+)?update|hotfix"
        r"|\d+(?:\.\d+)+)?$",
        re.I,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._versions: Optional[List[ScrapedFirmware]] = None

    @staticmethod
    def _date(raw: Optional[str]) -> Optional[datetime]:
        if not raw:
            return None
        tokens = re.findall(r"[A-Za-z]+|\d+", raw)
        words = [t for t in tokens if t.isalpha()]
        numbers = [t for t in tokens if t.isdigit()]
        month = next((MONTHS[w[:3].lower()] for w in words if w[:3].lower() in MONTHS), None)

        def year_of(text: str) -> int:
            value = int(text)
            if len(text) == 4:
                return value
            return 1900 + value if value >= 90 else 2000 + value

        try:
            if month is not None and len(numbers) == 2:
                # A four-digit number is the year wherever it sits; otherwise the day
                # comes first and a two-digit year last.
                if len(numbers[0]) == 4:
                    year, day = year_of(numbers[0]), int(numbers[1])
                else:
                    day, year = int(numbers[0]), year_of(numbers[1])
                return datetime(year, month, day)
            if month is None and len(numbers) == 3 and len(numbers[0]) == 4:
                return datetime(int(numbers[0]), int(numbers[1]), int(numbers[2]))
        except ValueError:
            return None
        return None

    def _parse_heading(self, text: str) -> Optional[Tuple[str, Optional[datetime]]]:
        """(version, date) for a release heading; None for anything else."""
        if self.PRERELEASE.search(text):
            return None
        matched = self.HEADING.match(text)
        if not matched:
            return None
        version = matched.group("version")
        major, _, rest = version.partition(".")
        if len(major) == 4 and major.startswith("20"):
            version = f"{int(major) - 2000}.{rest}"  # "2024.2.2" is 24.2.2
        if not self.QUALIFIER.match(matched.group("rest").strip()):
            return None
        return version, self._date(matched.group("date"))

    def _notes(self, heading) -> List[str]:
        """The heading's following siblings, up to the next heading.

        Siblings rather than the page's paragraphs in order: from 20.x back, each
        release sits inside a list item with its notes beside it, and reading every
        paragraph that is not inside a list dropped all of them.
        """
        notes: List[str] = []
        for sibling in heading.find_next_siblings():
            if sibling.name in ("h2", "h3"):
                break
            if sibling.name in ("ul", "ol"):
                notes.extend(
                    "- " + " ".join(item.get_text(" ").split())
                    for item in sibling.find_all("li", recursive=False)
                )
                continue
            text = " ".join(sibling.get_text(" ").split())
            if text:
                notes.append(text)
        return notes

    def _parse_whats_new(self, html: str) -> List[ScrapedFirmware]:
        soup = self.parse_html(html)
        releases: List[Tuple[str, Optional[datetime], List[str]]] = []
        for heading in soup.find_all(["h2", "h3"]):
            parsed = self._parse_heading(" ".join(heading.get_text(" ").split()))
            if parsed is not None:
                releases.append((parsed[0], parsed[1], self._notes(heading)))

        versions: Dict[str, ScrapedFirmware] = {}
        for version, released, notes in releases:
            changelog = "\n".join(notes) or None
            existing = versions.get(version)
            if existing is None:
                versions[version] = ScrapedFirmware(version=version, release_date=released, changelog=changelog)
                continue
            if released and (existing.release_date is None or released < existing.release_date):
                existing.release_date = released
            if changelog:
                existing.changelog = "\n".join(filter(None, [existing.changelog, changelog]))
        return list(versions.values())

    async def _load(self) -> Optional[List[ScrapedFirmware]]:
        if self._versions is None:
            html = await self.fetch_page(self.WHATS_NEW_URL)
            versions = self._parse_whats_new(html) if html else []
            self._versions = versions or None
        return self._versions

    async def fetch_device_list(self) -> ScraperResult:
        if await self._load() is None:
            return ScraperResult(success=False, error=f"No FL Studio releases found at {self.WHATS_NEW_URL}")
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=self.PRODUCT_NAME,
                    category="vst_plugin",
                    firmware_page_url=self.WHATS_NEW_URL,
                    product_url=self.PRODUCT_URL,
                )
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        versions = await self._load()
        if versions is None:
            return ScraperResult(success=False, error=f"No FL Studio releases found at {self.WHATS_NEW_URL}")
        if device_name != self.PRODUCT_NAME:
            return ScraperResult(success=True, firmware_versions=[])
        return ScraperResult(success=True, firmware_versions=list(versions))
