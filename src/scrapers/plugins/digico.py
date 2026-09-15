import re
from datetime import datetime
from typing import Dict, List, Optional, Set

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class DigicoScraper(BaseScraper):
    """DiGiCo consoles, from the console software articles on its Zendesk help centre.

    support.digico.biz is Zendesk, and robots.txt allows its articles API (only the
    per-article view stats are disallowed). Each console software release is its own
    article, and the offline editors have articles of their own beside them:

        SD Console Software V2126             "Release Date: Dec 2025"
        Quantum Console Software Version V1742
        S-Series Console Software V3.1.1
        V22 Quantum Console Software          "v2242 Errors Fixed", "v2232 Errors Fixed"
        SD Offline Software V2126             the editor -- not read

    **Four software lines, as devices:** SD Range, Quantum Range, Quantum 852 and
    S-Series. S21 and S31 had separate articles at V2.6.1 and share one "S-Series"
    article since. Quantum 852 had its own V1879 and V1889 and is otherwise on the
    Quantum train -- every Quantum article from V1742 on lists it among its download
    links -- and the numbering is one sequence (V1742, V1879, V1889, V1926), so it gets
    both.

    **A version is a four-digit build or a dotted S-Series number, from the title.**
    V22 broke the pattern: its title names only the major, and the body holds the
    builds as section headings, "v2242 Errors Fixed" above "v2232 Errors Fixed". The
    newest build carries the article's release date; the earlier one is undated, since
    the article states one date.

    **Dates are month precision**, from "Release Date: Dec 2025", stored as the first of
    the month. SD and Quantum release the same versions together, and on 2026-09-15 the
    two disagree once: SD V2025 says Nov 2024 -- the date of V1926 -- and Quantum V2025
    says March 2025. A version whose articles state different dates is left undated
    rather than given either. Quantum 852 V1879 and V1889 and the S21/S31 V2.6.1
    articles give no date.

    Notes start at the first section heading, so the date line and the list of consoles
    to download for are left out.
    """

    manufacturer_name = "DiGiCo"
    manufacturer_slug = "digico"
    manufacturer_website = "https://digico.biz"

    ARTICLES_URL = "https://support.digico.biz/api/v2/help_center/en-gb/articles.json?per_page=100"
    MAX_PAGES = 20

    TITLE = re.compile(
        r"^(?:V(?P<major>\d+)\s+)?(?P<family>SD|Quantum\s+852|Quantum|S[- ]Series|S21|S31)\s+"
        r"Console\s+Software(?:\s+Version)?(?:\s+V(?P<version>\d+(?:\.\d+)*))?$",
        re.I,
    )
    FAMILIES = {
        "sd": "SD Range",
        "quantum": "Quantum Range",
        "quantum 852": "Quantum 852",
        "s-series": "S-Series",
        "s series": "S-Series",
        "s21": "S-Series",
        "s31": "S-Series",
    }
    QUANTUM_852_LINK = "Quantum 852"
    BUILD_HEADING = re.compile(r"^v(\d{4})\b", re.I)
    RELEASE_DATE = re.compile(
        r"Release\s+Date:\s*(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(?P<year>\d{4})",
        re.I,
    )
    MONTHS = {m: i for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
    NOTES_LIMIT = 4000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._catalogue: Optional[Dict[str, dict]] = None

    @staticmethod
    def _text(element) -> str:
        return " ".join(element.get_text(" ", strip=True).split())

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(part) for part in version.split("."))

    def _lines(self, element) -> List[str]:
        if element.name in ("ul", "ol"):
            return ["- " + text for text in (self._text(li) for li in element.find_all("li", recursive=False)) if text]
        text = self._text(element)
        return [text] if text else []

    def _join(self, lines: List[str]) -> Optional[str]:
        text = "\n".join(lines)
        if len(text) > self.NOTES_LIMIT:
            cut = text.rfind("\n", 0, self.NOTES_LIMIT + 1)
            text = text[:cut] if cut > 0 else text[: self.NOTES_LIMIT]
        return text or None

    def _parse_article(self, title_match, body: str) -> List[ScrapedFirmware]:
        soup = self.parse_html(body)
        dated = self.RELEASE_DATE.search(" ".join(soup.get_text(" ", strip=True).split()))
        release_date = (
            datetime(int(dated.group("year")), self.MONTHS[dated.group("month")[:3].lower()], 1)
            if dated else None
        )

        # Notes start at the first section heading; above it are the date and the list
        # of consoles to download for. A "v2242 Errors Fixed" heading starts that
        # build's own section.
        shared: List[str] = []
        builds: Dict[str, List[str]] = {}
        current: Optional[List[str]] = None
        started = False
        for element in (soup.body.find_all(recursive=False) if soup.body else []):
            if element.name in ("h3", "h4", "h5"):
                started = True
                heading = self._text(element)
                build = self.BUILD_HEADING.match(heading)
                if build:
                    current = builds.setdefault(build.group(1), [])
                if heading:
                    (current if current is not None else shared).append(heading)
                continue
            if started:
                (current if current is not None else shared).extend(self._lines(element))

        version = title_match.group("version")
        major = title_match.group("major")
        if version:
            lines = shared + [line for section in builds.values() for line in section]
            return [ScrapedFirmware(version=version, release_date=release_date, changelog=self._join(lines))]
        if not major:
            return []

        numbers = sorted((b for b in builds if b.startswith(major)), key=int, reverse=True)
        return [
            ScrapedFirmware(
                version=number,
                release_date=release_date if index == 0 else None,
                changelog=self._join((shared if index == 0 else []) + builds[number]),
            )
            for index, number in enumerate(numbers)
        ]

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

        releases: Dict[str, Dict[str, ScrapedFirmware]] = {}
        pages_for: Dict[str, Dict[str, str]] = {}
        stated: Dict[str, Set[datetime]] = {}
        for article in articles:
            match = self.TITLE.match(" ".join((article.get("title") or "").split()))
            if not match:
                continue
            body = article.get("body") or ""
            devices = [self.FAMILIES[" ".join(match.group("family").lower().split())]]
            if devices[0] == "Quantum Range":
                # The consoles an article is for are its download buttons.
                links = {self._text(span) for span in self.parse_html(body).select("span.download-link")}
                if self.QUANTUM_852_LINK in links:
                    devices.append("Quantum 852")

            for firmware in self._parse_article(match, body):
                if firmware.release_date:
                    stated.setdefault(firmware.version, set()).add(firmware.release_date)
                for device in devices:
                    known = releases.setdefault(device, {})
                    if firmware.version not in known or (firmware.changelog and not known[firmware.version].changelog):
                        known[firmware.version] = ScrapedFirmware(
                            version=firmware.version,
                            release_date=firmware.release_date,
                            changelog=firmware.changelog,
                        )
                    pages_for.setdefault(device, {})[firmware.version] = article.get("html_url")

        catalogue: Dict[str, dict] = {}
        for device, known in releases.items():
            versions = sorted(known.values(), key=lambda fw: self._version_key(fw.version), reverse=True)
            for firmware in versions:
                if len(stated.get(firmware.version, ())) > 1:
                    # The vendor gives this version two dates; neither is trusted.
                    firmware.release_date = None
            catalogue[device] = {"url": pages_for[device][versions[0].version], "versions": versions}

        if not catalogue:
            return None
        self._catalogue = catalogue
        return catalogue

    async def fetch_device_list(self) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(success=False, error=f"No console software articles read from {self.ARTICLES_URL}")
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    # Mixing consoles: none of the other categories fits.
                    name=name,
                    category="other",
                    firmware_page_url=entry["url"],
                    product_url=entry["url"],
                )
                for name, entry in catalogue.items()
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(success=False, error=f"No console software articles read from {self.ARTICLES_URL}")
        entry = catalogue.get(device_name)
        if entry is None:
            return ScraperResult(success=False, error=f"No console software articles found for {device_name}")
        return ScraperResult(success=True, firmware_versions=entry["versions"])
