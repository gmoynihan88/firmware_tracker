import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


@dataclass
class _Release:
    name: str
    version: str
    released: Optional[datetime]
    history_url: Optional[str]


class NordScraper(BaseScraper):
    """Nord (Clavia) -- the OS of every keyboard, synth and drum, current and legacy.

    `/downloads/` links a downloads page for each of 9 current and 28 legacy products.
    Each carries an "OS Update" accordion with the update files, a statement of the
    latest version, and for 13 products a link to an update-history page:

        <h2>OS Update</h2>
        <p>macOS (2026-08-25)<br/><a href="...">Update Nord Stage 4 OS v1.66.dmg</a></p>
        <p><b>Nord Stage 4 OS Update</b><br/>Latest version: 1.66<br/>Released: 2026-08-25</p>
        <a href="/update-history/nord-stage-4-update-history/">Update history</a>

        <h4>OS v1.66 (2026-08-25)</h4><ul><li>Updates to production test routines</li></ul>

    The history gives every release with its date and notes -- Nord Stage 4 back to
    0.90 in January 2023, Nord Lead A1 to 2014. Products without one get the version
    the statement names.

    **The product is named by the statement, not the page.** The Nord Grand 2 page's
    heading says "Nord Grand", the name of a legacy product with its own page, and the
    `nord-c` page says "Nord C2D", which is another. The statement says "Nord Grand 2
    OS Update" and "Nord C2 OS Update" -- or "Nord Modular OS", or nothing, in which case
    the accordion's own heading names it: "Nord Lead 2X OS".

    **One statement can cover two models.** Nord Electro 3 writes "Latest version 61/73:
    3.14 Latest version HP: 3.16", so where no statement names a single version, each
    update file names its model, version and date instead: "Update Nord Electro 3 OS
    v3.14", "Update Nord Electro 3HP OS v3.16". Nord Lead 3 has files and no statement
    at all, and no date.

    **"Final version: 1.00 Released: 2003-01-01"** is a placeholder. Nord Lead 2X says
    "No updates available" beside it and Nord Lead 2 "out of stock" (its last OS was an
    EEPROM chip), and both carry the same New Year's Day. A final version dated 1
    January is stored undated.

    **Versions are written with two decimals, except when they are not.** The statement
    says 2.0 and 3.0 where the files and histories say v2.00 and v3.00, and C2D's first
    history heading is "v1.0". A one-digit minor is padded, so the same release is not
    stored twice.

    **A history date beats the statement's.** Nord Wave 2's statement says 1.24 shipped
    2024-05-21; its history says 2024-05-11. The history is the release record, the
    statement the download's upload.

    Notes that mention versions -- "Program format was updated to v3.08" -- are notes;
    only a heading that is nothing but a version (and a date) is a release. A product
    page that fails to load is skipped with a warning; its device keeps what it had.
    """

    manufacturer_name = "Nord"
    manufacturer_slug = "nord"
    manufacturer_website = "https://www.nordkeyboards.com"

    BASE_URL = "https://www.nordkeyboards.com"
    DOWNLOADS_URL = BASE_URL + "/downloads/"

    PRODUCT_PAGE = re.compile(r"^/(?:legacy-)?products/[^/?#]+/downloads/?$")
    STATEMENT_NAME = re.compile(r"^(?P<name>Nord\s.+?)\s+OS(?:\s+update)?(?:\s*\(legacy\))?$", re.I)
    STATEMENT = re.compile(
        r"(?P<kind>Latest|Final)\s+version:\s*(?P<version>\d+\.\d+)\s+Released:\s*(?P<date>\d{4}-\d{2}-\d{2})", re.I)
    UPDATE_FILE = re.compile(
        r"^(?:Update\s+)?(?P<name>Nord\s.+?)\s+OS\s+v(?P<version>\d+\.\d+)(?:\s+Update)?(?:\s*\(.*\))?(?:\.\w{2,4})?$", re.I)
    HISTORY_HEADING = re.compile(
        r"^(?:OS\s+)?v(?P<version>\d+\.\d+)(?:\s*\((?P<date>\d{4}-\d{2}-\d{2})\))?$", re.I)
    DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
    NOTES_LIMIT = 4000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._devices: Optional[Dict[str, Tuple[str, List[ScrapedFirmware]]]] = None

    # --- parsing ------------------------------------------------------------

    @staticmethod
    def _normal(version: str) -> str:
        return re.sub(r"^(\d+)\.(\d)$", r"\1.\g<2>0", version)

    @staticmethod
    def _date(text: Optional[str]) -> Optional[datetime]:
        try:
            return datetime.strptime(text, "%Y-%m-%d") if text else None
        except ValueError:
            return None

    def _parse_listing(self, html: str) -> List[str]:
        urls: List[str] = []
        for link in self.parse_html(html).find_all("a", href=True):
            path = link["href"].split("?")[0].split("#")[0].replace(self.BASE_URL, "")
            if self.PRODUCT_PAGE.match(path):
                url = self.BASE_URL + path.rstrip("/")
                if url not in urls:
                    urls.append(url)
        return urls

    def _parse_downloads(self, html: str) -> List[_Release]:
        """The OS release(s) a product's downloads page states."""
        soup = self.parse_html(html)
        heading = next((h for h in soup.find_all("h2") if re.search(r"\bOS\b", h.get_text())), None)
        if heading is None:
            return []
        box = heading.find_parent(class_=re.compile(r"Accordion__Container")) or heading.parent
        text = " ".join(box.get_text(" ").split())
        history = next((urljoin(self.BASE_URL, a["href"]) for a in box.find_all("a", href=True)
                        if "update-history" in a["href"]), None)

        stated = self.STATEMENT.search(text)
        if stated:
            # The statement's own bold name, else the accordion's heading: "Nord Lead 2X OS".
            for label in [*box.find_all(["b", "strong"]), heading]:
                named = self.STATEMENT_NAME.match(" ".join(label.get_text(" ").split()))
                if named:
                    placeholder = stated.group("kind").lower() == "final" and stated.group("date").endswith("-01-01")
                    return [_Release(named.group("name"), self._normal(stated.group("version")),
                                     None if placeholder else self._date(stated.group("date")), history)]

        # No single statement: each update file names its model, version and date.
        releases: Dict[str, _Release] = {}
        for link in box.find_all("a", href=True):
            named = self.UPDATE_FILE.match(" ".join(link.get_text(" ").split()))
            if not named or named.group("name") in releases:
                continue
            date_text = next((node for node in link.find_all_previous(string=self.DATE)
                              if any(parent is box for parent in node.parents)), None)
            found = self.DATE.search(date_text) if date_text else None
            releases[named.group("name")] = _Release(
                named.group("name"), self._normal(named.group("version")),
                self._date(found.group(0)) if found else None, None)
        return list(releases.values())

    def _parse_history(self, html: str) -> List[ScrapedFirmware]:
        soup = self.parse_html(html)
        versions: Dict[str, ScrapedFirmware] = {}
        for heading in (soup.find("main") or soup).find_all(["h2", "h3", "h4", "h5"]):
            matched = self.HISTORY_HEADING.match(" ".join(heading.get_text(" ").split()))
            if not matched:
                continue
            version = self._normal(matched.group("version"))
            if version in versions:
                continue
            notes: List[str] = []
            for sibling in heading.find_next_siblings():
                if sibling.name in ("h1", "h2", "h3", "h4", "h5"):
                    break
                line = " ".join(sibling.get_text(" ").split())
                if line:
                    notes.append(line)
            versions[version] = ScrapedFirmware(
                version=version, release_date=self._date(matched.group("date")),
                changelog="\n".join(notes)[: self.NOTES_LIMIT] or None,
            )
        return list(versions.values())

    @staticmethod
    def _order(versions: List[ScrapedFirmware]) -> List[ScrapedFirmware]:
        return sorted(versions, key=lambda fw: [int(n) for n in re.findall(r"\d+", fw.version)], reverse=True)

    # --- loading ------------------------------------------------------------

    async def _load(self) -> Optional[Dict[str, Tuple[str, List[ScrapedFirmware]]]]:
        if self._devices is not None:
            return self._devices

        listing = await self.fetch_page(self.DOWNLOADS_URL)
        pages = self._parse_listing(listing) if listing else []
        if not pages:
            return None

        devices: Dict[str, Tuple[str, Dict[str, ScrapedFirmware]]] = {}
        for page_url in pages:
            html = await self.fetch_page(page_url)
            if not html:
                logger.warning("Nord downloads page %s did not load", page_url)
                continue
            for release in self._parse_downloads(html):
                versions: Dict[str, ScrapedFirmware] = {}
                if release.history_url:
                    history = await self.fetch_page(release.history_url)
                    versions = {fw.version: fw for fw in self._parse_history(history or "")}
                current = versions.get(release.version)
                if current is None:
                    versions[release.version] = ScrapedFirmware(version=release.version, release_date=release.released)
                elif current.release_date is None:
                    current.release_date = release.released

                _url, known = devices.setdefault(release.name, (page_url, {}))
                for version, firmware in versions.items():
                    known.setdefault(version, firmware)

        self._devices = {name: (url, self._order(list(versions.values())))
                         for name, (url, versions) in devices.items()} or None
        return self._devices

    async def fetch_device_list(self) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error=f"No Nord OS releases found from {self.DOWNLOADS_URL}")
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(name=name, category="synthesizer", firmware_page_url=url, product_url=url)
                for name, (url, _versions) in sorted(devices.items())
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error=f"No Nord OS releases found from {self.DOWNLOADS_URL}")
        _url, versions = devices.get(device_name, (None, []))
        return ScraperResult(success=True, firmware_versions=list(versions))
