import logging
import re
from datetime import datetime
from typing import Dict, List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class SoundtoysScraper(BaseScraper):
    """Soundtoys, whose plug-ins ship and update as one suite: Soundtoys 5.

    Every product page -- Decapitator, EchoBoy, SpaceBlender, the bundle -- states
    the same "Current Version: 5.5" and links the same Release Log, so the catalogue
    has one device for the suite rather than one history copied onto every plug-in.

    `/release-log/` is one WordPress page, newest first, back to 5.0.1 in 2015. Each
    release is a paragraph holding only bold text, the date in the paragraph after
    it, then its notes until the next heading:

        <p><strong>Soundtoys 5.5.4 Update</strong></p>
        <p>November 25, 2025</p>
        <p>Improvements:</p><ul><li>...</li></ul>

    It was written by hand over eleven years, and reads that way:

    - **Headings name the version five ways**: "Soundtoys 5.5.5 Update", "5.4 Update",
      "SpaceBlender Software Update (5.5.1.18546)", "Maintenance Update 5.2.4.13665
      (Mac) and 5.2.4.13670 (PC)". The fourth number is a build, which differs between
      the Mac and PC builds of one release, so versions are kept to three.
    - **Dates are written five ways**: "July 7, 2026", "June 05, 2025", "June 20th,
      2024", "October, 20, 2021", and "June 2, 2016:" inside <em>. A pattern for the
      first form alone left five releases undated; four of them had a date all along.
    - **Some releases open with a note before their date**: "(Free update for all
      version 5 product owners)", "NOTE: This update is effectively the same as
      5.2.3...". The date is the first paragraph that is nothing but a date, before the
      release's first list -- so a date further into the notes is never taken for the
      release's.
    - **5.5.2 has no date.** Its first paragraph is "Features:". It stays undated.
    - **5.0.1 appears twice**: for Mac and PC on October 13, 2015, then again for PC
      alone on October 30. It is one version, dated by its first release, with both
      sets of notes.
    - **Not every heading is a release.** "Outer Limits Preset Expander" is a preset
      pack, with no version. Only headings naming an update or release, with a
      version, are read.

    Ruled out, 2026-09-13: the WordPress REST API has no product or version routes
    (its namespaces are cookie banners, redirects, SEO and two-factor plug-ins), and
    `/product/` pages state only "5.5".
    """

    manufacturer_name = "Soundtoys"
    manufacturer_slug = "soundtoys"
    manufacturer_website = "https://www.soundtoys.com"

    RELEASE_LOG_URL = "https://www.soundtoys.com/release-log/"
    PRODUCT_URL = "https://www.soundtoys.com/product/soundtoys-5/"
    PRODUCT_NAME = "Soundtoys 5"

    # The first version named, to three numbers: "5.2.4.13665 (Mac) and 5.2.4.13670 (PC)" is 5.2.4.
    VERSION = re.compile(r"\b(\d+\.\d+(?:\.\d+)?)(?:\.\d+)?\b")
    RELEASE_WORD = re.compile(r"\b(?:update|release)\b", re.I)
    DATE = re.compile(r"^([A-Za-z]+),?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4}):?$")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._versions: Optional[List[ScrapedFirmware]] = None

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(part) for part in version.split("."))

    @staticmethod
    def _heading(element) -> Optional[str]:
        """A release heading is a paragraph holding nothing but bold text."""
        if element.name != "p":
            return None
        strong = element.find("strong")
        if strong is None:
            return None
        text = " ".join(strong.get_text(" ").split())
        return text if text and text == " ".join(element.get_text(" ").split()) else None

    def _date(self, text: str) -> Optional[datetime]:
        matched = self.DATE.match(text)
        if not matched:
            return None
        month, day, year = matched.groups()
        for fmt in ("%B %d %Y", "%b %d %Y"):
            try:
                return datetime.strptime(f"{month} {day} {year}", fmt)
            except ValueError:
                continue
        return None

    def _parse_release_log(self, html: str) -> List[ScrapedFirmware]:
        soup = self.parse_html(html)
        section = soup.select_one("section.block-freepage")
        if section is None:
            return []

        releases: List[dict] = []
        current: Optional[dict] = None
        # Direct children only: a nested list would otherwise be read twice.
        for element in section.find_all(["p", "ul", "ol"], recursive=False):
            heading = self._heading(element)
            if heading is not None:
                current = {"heading": heading, "date": None, "notes": [], "awaiting_date": True}
                releases.append(current)
                continue
            if current is None:
                continue
            text = " ".join(element.get_text(" ").split())
            if not text:
                continue
            if current["awaiting_date"]:
                if element.name in ("ul", "ol"):
                    current["awaiting_date"] = False
                else:
                    date = self._date(text)
                    if date is not None:
                        current["date"] = date
                        current["awaiting_date"] = False
                        continue
            if element.name in ("ul", "ol"):
                current["notes"].extend(
                    "- " + " ".join(item.get_text(" ").split())
                    for item in element.find_all("li", recursive=False)
                )
            else:
                current["notes"].append(text)

        versions: Dict[str, ScrapedFirmware] = {}
        for release in releases:
            matched = self.VERSION.search(release["heading"])
            if not matched or not self.RELEASE_WORD.search(release["heading"]):
                continue
            version = matched.group(1)
            notes = "\n".join(release["notes"]) or None
            existing = versions.get(version)
            if existing is None:
                versions[version] = ScrapedFirmware(
                    version=version, release_date=release["date"], changelog=notes
                )
                continue
            # Newest first, so a version repeated further down is its first release.
            if release["date"] and (existing.release_date is None or release["date"] < existing.release_date):
                existing.release_date = release["date"]
            if notes:
                existing.changelog = "\n".join(filter(None, [existing.changelog, notes]))

        return sorted(versions.values(), key=lambda fw: self._version_key(fw.version), reverse=True)

    async def _load(self) -> Optional[List[ScrapedFirmware]]:
        if self._versions is None:
            html = await self.fetch_page(self.RELEASE_LOG_URL)
            versions = self._parse_release_log(html) if html else []
            self._versions = versions or None
        return self._versions

    async def fetch_device_list(self) -> ScraperResult:
        if await self._load() is None:
            return ScraperResult(success=False, error=f"No releases found at {self.RELEASE_LOG_URL}")
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=self.PRODUCT_NAME,
                    category="vst_plugin",
                    firmware_page_url=self.RELEASE_LOG_URL,
                    product_url=self.PRODUCT_URL,
                )
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        versions = await self._load()
        if versions is None:
            return ScraperResult(success=False, error=f"No releases found at {self.RELEASE_LOG_URL}")
        if device_name != self.PRODUCT_NAME:
            return ScraperResult(success=True, firmware_versions=[])
        return ScraperResult(success=True, firmware_versions=list(versions))
