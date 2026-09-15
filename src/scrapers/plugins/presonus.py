import json
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import quote

from bs4 import NavigableString

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)

MONTHS = {name: number for number, name in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


class PreSonusScraper(BaseScraper):
    """PreSonus -- Fender Studio, Fender Notion and Notion 6, from its published release notes.

    **What PreSonus does not publish, checked 2026-09-14.** Studio One Pro 7 and its
    successor Fender Studio Pro 8 have no public release notes: the help center's
    Studio One categories (184 sections) hold tutorials and one "where is the manual"
    article; presonus.com's sitemap has only blog posts ("What's new in Studio One Pro
    7.1"); and `api.presonus.com/studioone7/change_log.html`, modelled on Notion's, answers
    with the same five bytes as a made-up product. Hardware firmware is not listed
    either -- StudioLive, Quantum and Revelator articles are update how-tos, and the one
    version table ("Universal Control and the corresponding firmware versions") stopped
    in 2021. Studio One 4's version history is published but ended in 2019 and is not
    read: a device called Studio One reporting 4.5.4 would mislead anyone on 6 or 7.

    **What it does publish, and is read:**

    - **Fender Studio** -- help-center article "Fender Studio Release Notes": a bold
      `1.3 (113142/113218) Jul 30, 2026` per release, then a table of issues.
    - **Fender Notion** -- "Fender Notion Release Notes", the whole mobile lineage back
      to Notion for iOS 1.0 in 2011, headed four ways: "Fender Notion 3.7.1: Aug 2026",
      "Notion Mobile 3.0.4:", "Version 2.6.2 (Oct 19th 2021)", "Version 2.0.157 (Oct 17
      2016)" -- and once "ersion 1.2.66 (Jul 31, 2013)", its V lost. A month and year is
      stored on the first of the month; "Notion Mobile 3.0.4:" has no date and none is
      invented. "(Android only)" is a note, not a date.
    - **Notion 6** -- the desktop app's `change_log.html`, a preformatted page of `<big><b>6.8.2
      Build 18133</b> <b>Aug 24, 2021</b></big>` entries. 6.8.2 is the last; the version is
      the dotted number, not the build.

    Articles are found by exact title through the help center's search API, whose
    results carry the body, so a renumbered article is still found and a similarly
    titled one ("Fender Notion is here...") is not taken for it. A source that cannot be
    read is skipped with a warning; the scrape fails only when none can be.
    """

    manufacturer_name = "PreSonus"
    manufacturer_slug = "presonus"
    manufacturer_website = "https://www.presonus.com"

    SEARCH_URL = "https://support.presonus.com/api/v2/help_center/articles/search.json?query={query}&per_page=10"
    NOTION6_URL = "https://api.presonus.com/notion6/change_log.html"
    ARTICLES = {"Fender Studio": "Fender Studio Release Notes", "Fender Notion": "Fender Notion Release Notes"}
    NOTION6 = "Notion 6"

    STUDIO_HEADING = re.compile(r"^(?P<version>\d+(?:\.\d+)+)\s*\(\s*[\d/ ]+\)\s*(?P<when>.+)$")
    NOTION_HEADING = re.compile(
        r"^(?:Fender\s+Notion|Notion\s+Mobile|V?ersion)\s+(?P<version>\d+(?:\.\d+)+)\s*"
        r"(?::\s*(?P<when>[^()]*?))?\s*(?:\((?P<paren>[^)]*)\))?\s*$", re.I)
    NOTION6_VERSION = re.compile(r"^(?P<version>\d+(?:\.\d+)+)(?:\s+Build\s+\d+)?$", re.I)
    FULL_DATE = re.compile(r"\b(?P<month>[A-Za-z]{3,9})\.?\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<year>\d{4})\b")
    MONTH_DATE = re.compile(r"\b(?P<month>[A-Za-z]{3,9})\.?\s+(?P<year>\d{4})\b")
    NOTES_LIMIT = 4000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._products: Optional[Dict[str, List[ScrapedFirmware]]] = None

    # --- parsing ------------------------------------------------------------

    @classmethod
    def search_url(cls, title: str) -> str:
        return cls.SEARCH_URL.format(query=quote(title))

    @classmethod
    def _date(cls, text: str) -> Optional[datetime]:
        """A day-precise date if the text has one, else the first of a named month."""
        for pattern in (cls.FULL_DATE, cls.MONTH_DATE):
            for matched in pattern.finditer(text or ""):
                month = MONTHS.get(matched.group("month")[:3].lower())
                if not month:
                    continue
                try:
                    day = int(matched.group("day")) if "day" in matched.groupdict() else 1
                    return datetime(int(matched.group("year")), month, day)
                except ValueError:
                    continue
        return None

    @staticmethod
    def _lines(element) -> List[str]:
        if element.name == "figure" or element.find("table"):
            rows = [" ".join(" ".join(cell.get_text(" ").split()) for cell in row.find_all(["td", "th"]))
                    for row in element.find_all("tr")]
            return [row for row in rows if row and row.lower() != "issue type issue key summary"]
        return [line.strip() for line in element.get_text("\n").split("\n") if line.strip()]

    def _parse_article(self, body: str, heading: re.Pattern) -> List[ScrapedFirmware]:
        """Releases headed by a bold line; notes run to the next such heading."""
        soup = self.parse_html(body)
        marks = [(bold, heading.match(" ".join(bold.get_text(" ").split())))
                 for bold in soup.find_all(["strong", "b"])]
        marks = [(bold, matched) for bold, matched in marks if matched]
        containers = {id(bold.find_parent("p") or bold.parent) for bold, _ in marks}

        versions: Dict[str, ScrapedFirmware] = {}
        for bold, matched in marks:
            version = matched.group("version")
            if version in versions:
                continue
            container = bold.find_parent("p") or bold.parent
            title = " ".join(bold.get_text(" ").split())
            notes = [line for line in self._lines(container)
                     if " ".join(line.split()) != title and not re.match(r"^(?:(?:Release\s+)?Guide:|https?://\S+$)", line)]
            for sibling in container.find_next_siblings():
                if id(sibling) in containers or any(id(p) in containers for p in sibling.find_all("p")):
                    break
                notes.extend(self._lines(sibling))
            when = " ".join(filter(None, (matched.groupdict().get("when"), matched.groupdict().get("paren"))))
            versions[version] = ScrapedFirmware(
                version=version, release_date=self._date(when),
                changelog="\n".join(notes)[: self.NOTES_LIMIT] or None,
            )
        return list(versions.values())

    def _parse_notion6(self, html: str) -> List[ScrapedFirmware]:
        soup = self.parse_html(html)
        versions: Dict[str, ScrapedFirmware] = {}
        for big in soup.find_all("big"):
            bolds = [" ".join(b.get_text(" ").split()) for b in big.find_all("b")]
            matched = self.NOTION6_VERSION.match(bolds[0]) if bolds else None
            if not matched or matched.group("version") in versions:
                continue
            notes: List[str] = []
            for node in big.next_siblings:
                if getattr(node, "name", None) == "big":
                    break
                text = str(node) if isinstance(node, NavigableString) else node.get_text("\n")
                notes.extend(line.strip() for line in text.split("\n") if line.strip())
            versions[matched.group("version")] = ScrapedFirmware(
                version=matched.group("version"),
                release_date=self._date(" ".join(bolds[1:])),
                changelog="\n".join(notes)[: self.NOTES_LIMIT] or None,
            )
        return list(versions.values())

    # --- loading ------------------------------------------------------------

    async def _article_body(self, title: str) -> Optional[str]:
        body = await self.fetch_page(self.search_url(title))
        try:
            results = json.loads(body).get("results", []) if body else []
        except ValueError:
            return None
        return next((a.get("body") for a in results if (a.get("title") or "").strip() == title), None)

    async def _load(self) -> Optional[Dict[str, List[ScrapedFirmware]]]:
        if self._products is not None:
            return self._products

        products: Dict[str, List[ScrapedFirmware]] = {}
        headings = {"Fender Studio": self.STUDIO_HEADING, "Fender Notion": self.NOTION_HEADING}
        for name, title in self.ARTICLES.items():
            body = await self._article_body(title)
            releases = self._parse_article(body, headings[name]) if body else []
            if releases:
                products[name] = releases
            else:
                logger.warning("PreSonus help center article %r was not found or had no releases", title)

        changelog = await self.fetch_page(self.NOTION6_URL)
        releases = self._parse_notion6(changelog) if changelog else []
        if releases:
            products[self.NOTION6] = releases
        else:
            logger.warning("Notion 6 change log at %s did not load or had no releases", self.NOTION6_URL)

        self._products = products or None
        return self._products

    def _page_for(self, name: str) -> str:
        if name == self.NOTION6:
            return self.NOTION6_URL
        return "https://support.presonus.com/hc/en-us/search?query=" + quote(self.ARTICLES[name])

    async def fetch_device_list(self) -> ScraperResult:
        products = await self._load()
        if not products:
            return ScraperResult(success=False, error="No PreSonus release notes could be read")
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(name=name, category="vst_plugin", firmware_page_url=self._page_for(name),
                              product_url=self._page_for(name))
                for name in products
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        products = await self._load()
        if not products:
            return ScraperResult(success=False, error="No PreSonus release notes could be read")
        return ScraperResult(success=True, firmware_versions=list(products.get(device_name, [])))
