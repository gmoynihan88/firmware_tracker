import json
import logging
import re
from typing import Dict, List, Optional, Tuple

from bs4 import NavigableString

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class AudientScraper(BaseScraper):
    """Audient -- iD, EVO and ORIA firmware, from one change-log article per product.

    support.audient.com is Zendesk, and every interface with updatable firmware has an
    article titled "<Product> Firmware Change Log" -- or "- Firmware Changelog", written
    four ways across fifteen articles. The whole help centre is listed through
    ``/api/v2/help_center/en-us/articles.json`` (five pages of 100) and the change logs
    picked out by title, so a new product's article is found without being named here.

    **Each article was written by hand, in its own markup**, checked 2026-09-15:

        <h2><strong><span>v1.4.12</span></strong></h2><ul><li>...</li></ul>   EVO 8
        <p><strong><font size="4">V1.1.2<br></font></strong></p>
          <p><strong>Changes:</strong></p><ul>...</ul><hr>                    iD14 MKII
        <div><strong>V1.3.0</strong></div> ... <div><strong>_____</strong></div>   EVO 16
        <p><strong>Release Notes - iD14 - Version v1.1.1</strong></p>        iD14 MKI
        <p>The Changelog for iD44 MKII can be seen below.<br><br>v1.0.2: </p>  iD44 MKII

    So the body is flattened to lines -- one per block and per ``<br>``, never splitting
    inline tags, because "Fixed <span>firmware</span> update failure" is one note -- and
    a line that opens with a version starts a release -- EVO 16 writes one as "V1.1.0 -
    Initial factory firmware release.", note and all. Rules of underscores go, and so do
    the "·" and "-" bullets typed in place of lists.

    **Undated.** No article gives a release date. Their ``created_at`` and ``edited_at``
    are when the article was written and last touched -- iD14 MKI's is 2015 and 2022,
    for a log that runs to v1.1.1 -- so they date nothing.

    **Firmware only.** The help centre also keeps "iD Driver - Change Log", "EVO Drivers
    - Change Log", "ORIA Control Desktop Software Changelog" and "Audient DFU Application
    - Change Log". Those are computer software numbered on their own track (EVO driver
    V4.3.10 beside EVO 8 firmware v1.4.12), not the interfaces' firmware, and the title
    pattern leaves them out.

    Two titles name their product in an older style: "ID4" for the original iD4, and
    "iD14 (MKI)". They are renamed to match "iD44 MKI" beside the MKII models.
    """

    manufacturer_name = "Audient"
    manufacturer_slug = "audient"
    manufacturer_website = "https://audient.com"

    ARTICLES_URL = "https://support.audient.com/api/v2/help_center/en-us/articles.json?per_page=100"
    MAX_PAGES = 20
    TITLE = re.compile(r"^(?P<name>.+?)\s*-?\s*Firmware\s+Change\s*log$", re.I)
    HEADING = re.compile(
        r"^(?:Release\s+Notes\s*-\s*.+?\s*-\s*Version\s+)?[vV](?P<version>\d+(?:\.\d+)+)\s*(?:[:\-–]\s*(?P<note>.*))?$"
    )
    RULE = re.compile(r"^[_\-–—]{3,}$")
    BULLET = re.compile(r"^[·•\-–]\s*")
    RENAMES = {"ID4": "iD4 MKI", "iD14 (MKI)": "iD14 MKI"}
    CATEGORIES = {"EVO SP8": "other"}
    BLOCKS = ("p", "li", "ul", "ol", "div", "hr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "tr")
    NOTES_LIMIT = 4000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._devices: Optional[Dict[str, Tuple[str, List[ScrapedFirmware]]]] = None

    # --- parsing ------------------------------------------------------------

    def _product_name(self, title: str) -> Optional[str]:
        matched = self.TITLE.match(" ".join(title.split()))
        if not matched:
            return None
        name = matched.group("name")
        return self.RENAMES.get(name, name)

    def _lines(self, body: str) -> List[str]:
        soup = self.parse_html(body)
        for br in soup.find_all("br"):
            br.replace_with(NavigableString("\n"))
        for block in soup.find_all(self.BLOCKS):
            block.insert_before(NavigableString("\n"))
            block.insert_after(NavigableString("\n"))
        lines = (" ".join(line.split()) for line in soup.get_text().splitlines())
        return [line for line in lines if line]

    def _parse_article(self, body: str) -> List[ScrapedFirmware]:
        releases: List[ScrapedFirmware] = []
        notes: Dict[str, List[str]] = {}
        current: Optional[str] = None
        for line in self._lines(body):
            heading = self.HEADING.match(line)
            if heading:
                current = heading.group("version")
                if current not in notes:
                    notes[current] = []
                    releases.append(ScrapedFirmware(version=current, release_date=None))
                if heading.group("note"):
                    notes[current].append(heading.group("note"))
                continue
            if current is None or self.RULE.match(line):
                continue
            note = self.BULLET.sub("", line)
            if note:
                notes[current].append(note)
        for release in releases:
            release.changelog = "\n".join(notes[release.version])[: self.NOTES_LIMIT] or None
        return releases

    # --- loading ------------------------------------------------------------

    async def _load(self) -> Optional[Dict[str, Tuple[str, List[ScrapedFirmware]]]]:
        if self._devices is not None:
            return self._devices
        articles: List[dict] = []
        page_count = 1
        page = 1
        while page <= min(page_count, self.MAX_PAGES):
            url = self.ARTICLES_URL if page == 1 else f"{self.ARTICLES_URL}&page={page}"
            body = await self.fetch_page(url)
            try:
                data = json.loads(body) if body else None
            except ValueError:
                data = None
            if not isinstance(data, dict):
                if page == 1:
                    return None
                logger.warning("Audient help centre page %s did not load", page)
                break
            articles.extend(data.get("articles") or [])
            page_count = data.get("page_count") or 1
            page += 1
        devices: Dict[str, Tuple[str, List[ScrapedFirmware]]] = {}
        for article in articles:
            name = self._product_name(article.get("title") or "")
            if not name or article.get("draft"):
                continue
            releases = self._parse_article(article.get("body") or "")
            if not releases:
                logger.warning("Audient change log %r named no version", article.get("title"))
                continue
            devices.setdefault(name, (article.get("html_url") or "", releases))
        self._devices = devices or None
        return self._devices

    async def fetch_device_list(self) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error="No Audient firmware change log found in the help centre")
        return ScraperResult(
            success=True,
            devices=[ScrapedDevice(name=name, category=self.CATEGORIES.get(name, "audio_interface"),
                                   firmware_page_url=url, product_url=url)
                     for name, (url, _releases) in devices.items()],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error="No Audient firmware change log found in the help centre")
        entry = devices.get(device_name)
        return ScraperResult(success=True, firmware_versions=entry[1] if entry else [])
