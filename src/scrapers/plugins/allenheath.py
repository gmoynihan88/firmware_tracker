import re
from datetime import datetime
from typing import Dict, List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult
from src.scrapers.notes import BLOCKS, join_notes, note_lines


class AllenHeathScraper(BaseScraper):
    """Allen & Heath mixers, from the firmware release-notes articles on its Zendesk.

    support.allen-heath.com is Zendesk, and each mixer family with published firmware
    has one article holding its whole history: "SQ Firmware Release Notes", "dLive
    Firmware Release Notes - Firmware Version 2.12", "GLD Release Notes – Firmware
    Version 1.63". The help centre is listed through ``/api/v2/help_center/articles.json``
    and the articles picked out by title, so a family's article is found without being
    named here. The main site's downloads pages sit behind a Cloudflare challenge; the
    help centre does not, and robots.txt allows its articles API.

    **A title must say Firmware.** "DT Preamp Control Release Notes" is the control
    app's history, numbered on its own track, and is left out.

    **Three heading shapes**, all h2 or h3, checked 2026-09-15:

        <h3><strong>V2.0.3</strong> Maintenance release</h3><h4>June 2026</h4>   SQ, SQ+, Qu-5/6/7
        <h2>Version 2.12 - Maintenance Release. January 2026</h2>               dLive, GLD, ME-U, Avantis
        <h3>V1.0.2 - February 2026</h3>                                         the Dante cards

    So a release is a heading that opens with a version, and its month and year come
    from the heading or, failing that, from the first line beneath it -- only the first,
    because later lines are the notes, and SQ's older releases open straight into
    "SQ-Drive:" with no date at all. A version quoted in prose ("Downgrading from V1.31
    or later...") is a paragraph, not a heading, and is not read. Dates are month
    precision, stored as the first of the month.

    The ML article says no release notes were ever published for its V1.40, so that
    version comes from the title alone.
    """

    manufacturer_name = "Allen & Heath"
    manufacturer_slug = "allenheath"
    manufacturer_website = "https://www.allen-heath.com"

    ARTICLES_URL = "https://support.allen-heath.com/api/v2/help_center/articles.json?per_page=100"
    MAX_PAGES = 30

    TITLE = re.compile(
        r"^(?P<name>.+?)\.?\s+(?:Firmware\s+(?:V(?P<version>\d+(?:\.\d+)+)\s+)?)?Release\s+Notes"
        r"(?:\s*[-–]\s*Firmware\s+Version\s+\d+(?:\.\d+)+)?$",
        re.I,
    )
    HEADING = re.compile(r"^(?:Version\s+|V)(?P<version>\d+(?:\.\d+)+)\b(?P<rest>.*)$", re.I)
    MONTH_YEAR = re.compile(
        r"\b(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(?P<year>\d{4})\b", re.I
    )
    MONTHS = {m: i for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
    NOTE_BLOCKS = ("p", "li", "h4")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._catalogue: Optional[Dict[str, dict]] = None

    @staticmethod
    def _text(element) -> str:
        return " ".join(element.get_text(" ", strip=True).split())

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(part) for part in re.findall(r"\d+", version)) or (0,)

    def _month(self, text: str) -> Optional[datetime]:
        match = self.MONTH_YEAR.search(text)
        if not match:
            return None
        return datetime(int(match.group("year")), self.MONTHS[match.group("month")[:3].lower()], 1)

    def _product(self, title: str) -> Optional[tuple]:
        """(name, title version) for a firmware release-notes article, else None."""
        title = " ".join(title.split())
        if "firmware" not in title.lower():
            return None
        match = self.TITLE.match(title)
        if not match:
            return None
        return match.group("name").strip(), match.group("version")

    def _parse_article(self, body: str) -> List[ScrapedFirmware]:
        soup = self.parse_html(body)
        headings = [h for h in soup.find_all(["h2", "h3"]) if self.HEADING.match(self._text(h))]
        releases: Dict[str, ScrapedFirmware] = {}

        for index, heading in enumerate(headings):
            match = self.HEADING.match(self._text(heading))
            version = match.group("version")
            release_date = self._month(match.group("rest"))
            stop = headings[index + 1] if index + 1 < len(headings) else None

            elements = []
            for element in heading.next_elements:
                if element is stop:
                    break
                elements.append(element)

            # Headings at the version's level or above are the article's own sections
            # ("Previous Versions"); the ones below it ("Fixes", "Known Issues") are notes.
            blocks = [b for b in BLOCKS if not (b.startswith("h") and b <= heading.name)]
            lines = note_lines(elements, blocks)

            # The month only counts as the first line of text, not counting section
            # headings -- the rule this parser has always dated by.
            first = next(
                (text for text in (self._text(e) for e in elements
                                   if getattr(e, "name", None) in self.NOTE_BLOCKS) if text),
                None,
            )
            if release_date is None and first and self.MONTH_YEAR.fullmatch(first):
                release_date = self._month(first)
                if first in lines:
                    lines.remove(first)

            if version not in releases:
                releases[version] = ScrapedFirmware(
                    version=version,
                    release_date=release_date,
                    changelog=join_notes(lines),
                )

        return sorted(releases.values(), key=lambda fw: self._version_key(fw.version), reverse=True)

    async def _load(self) -> Optional[Dict[str, dict]]:
        if self._catalogue is not None:
            return self._catalogue

        articles, url, pages = [], self.ARTICLES_URL, 0
        while url and pages < self.MAX_PAGES:
            data = await self.fetch_json(url)
            if not data:
                return None
            articles.extend(data.get("articles") or [])
            url, pages = data.get("next_page"), pages + 1

        catalogue: Dict[str, dict] = {}
        for article in articles:
            product = self._product(article.get("title") or "")
            if not product:
                continue
            name, title_version = product
            versions = self._parse_article(article.get("body") or "")
            if not versions and title_version:
                versions = [ScrapedFirmware(version=title_version)]
            if versions:
                catalogue[name] = {"url": article.get("html_url"), "versions": versions}

        if not catalogue:
            return None
        self._catalogue = catalogue
        return catalogue

    async def fetch_device_list(self) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(
                success=False, error=f"No firmware release notes read from {self.ARTICLES_URL}"
            )
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    # Consoles, personal mixers and option cards: none fits another category.
                    name=name,
                    category="other",
                    firmware_page_url=entry["url"],
                    product_url=entry["url"],
                )
                for name, entry in sorted(catalogue.items())
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(
                success=False, error=f"No firmware release notes read from {self.ARTICLES_URL}"
            )
        entry = catalogue.get(device_name)
        if entry is None:
            return ScraperResult(
                success=False, error=f"No firmware release notes found for {device_name}"
            )
        return ScraperResult(success=True, firmware_versions=entry["versions"])
