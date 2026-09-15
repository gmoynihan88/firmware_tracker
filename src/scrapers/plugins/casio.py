import re
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class CasioScraper(BaseScraper):
    """Casio keyboards, pianos and synths, from the musical-instrument downloads index.

    support.casio.com's Electronic Musical Instruments downloads page has a "Firmware
    Update" section, one link per model under category headings:

        <h2>Firmware Update</h2>
        <h3>Digital Pianos</h3>
        <a href="./download.php?cid=008&pid=435"><p>PX-5S Version 1.13 - <font>Oct. 2014</font></p></a>

    13 models on 2026-09-15: PX-5S, PX-560M, XW-G1, XW-P1, CT-S500, CT-S1000V, CT-X3000,
    CT-X5000, CT-X8000IN, CT-X9000IN, MZ-X300, MZ-X500 and XW-PD1. The rest of the page
    is data editors, drivers, song data and patch scripts, all with versions of their
    own. They share one <section> element with the firmware links, so the links read
    are the ones between the "Firmware Update" h2 and the next h2 -- scoping to the
    section read all 28 on the first live run.

    Each model's page states the current version in its heading, "[Firmware Update]
    PX-5S - Version 1.13", dates it in a right-aligned paragraph on two of them ("Oct.
    2014"), and lists what each update changed as rows headed "Version 1.12 >> Version
    1.13". The version a row updates *to* is a release; the one it updates *from* is not
    necessarily -- CT-S500 writes "Version 1.0x >> Version 1.06" -- so only the target
    is kept. Those older releases carry no date.

    casio.com's own musical-instrument support pages answer scripts with "Access Denied";
    this host does not, and has no robots.txt.
    """

    manufacturer_name = "Casio"
    manufacturer_slug = "casio"
    manufacturer_website = "https://www.casio.com"

    INDEX_URL = "https://support.casio.com/en/support/download.php?cid=008&pid=20"
    SECTION = "Firmware Update"

    LINK = re.compile(
        r"^(?P<name>.+?)\s+Version\s+(?P<version>\d+(?:\.\d+)+)"
        r"(?:\s*-\s*(?P<date>[A-Za-z]{3}\.?\s+\d{4}))?\s*-?$"
    )
    TITLE = re.compile(r"Version\s+(?P<version>\d+(?:\.\d+)+)\s*$")
    UPDATE_ROW = re.compile(r"^(?:Version\s+\S+\s*>>\s*)?Version\s+(?P<version>\d+(?:\.\d+)+)$")
    MONTH_YEAR = re.compile(r"^(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(?P<year>\d{4})$", re.I)
    MONTHS = {m: i for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

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
        match = self.MONTH_YEAR.match(" ".join((text or "").split()))
        if not match:
            return None
        return datetime(int(match.group("year")), self.MONTHS[match.group("month")[:3].lower()], 1)

    def _index_models(self, html: str) -> List[dict]:
        """Each model in the Firmware Update section: name, page, current version."""
        soup = self.parse_html(html)
        heading = soup.find(lambda tag: tag.name == "h2" and self._text(tag) == self.SECTION)
        if heading is None:
            return []
        models, seen = [], set()
        # Every heading on the page -- PC Application, Drivers, Data -- shares one
        # <section>, so the firmware links are the ones between this h2 and the next.
        for anchor in heading.find_all_next(["h2", "a"]):
            if anchor.name == "h2":
                break
            if not re.search(r"download\.php\?cid=008&pid=\d+", anchor.get("href") or ""):
                continue
            match = self.LINK.match(self._text(anchor))
            if not match or match.group("name") in seen:
                continue
            seen.add(match.group("name"))
            models.append({
                "name": match.group("name"),
                "url": urljoin(self.INDEX_URL, anchor["href"]),
                "version": match.group("version"),
                "date": self._month(match.group("date") or ""),
            })
        return models

    def _parse_model_page(self, html: str) -> Optional[List[ScrapedFirmware]]:
        """The current version with its date, then each earlier update's target version."""
        soup = self.parse_html(html)
        title = soup.find("h1")
        current = self.TITLE.search(self._text(title)) if title else None
        if not current:
            return None

        main = soup.select_one("div.column-main") or soup
        release_date = None
        for paragraph in main.find_all("p"):
            release_date = self._month(self._text(paragraph))
            if release_date:
                break

        releases: Dict[str, ScrapedFirmware] = {
            current.group("version"): ScrapedFirmware(version=current.group("version"), release_date=release_date)
        }
        notes: Dict[str, List[str]] = {current.group("version"): []}
        target = None
        for row in main.find_all("tr"):
            text = self._text(row)
            matched = self.UPDATE_ROW.match(text)
            if matched:
                target = matched.group("version")
                releases.setdefault(target, ScrapedFirmware(version=target))
                notes.setdefault(target, [])
                continue
            if target and text and "Improvements Provided" not in text:
                notes[target].append(text)

        for version, firmware in releases.items():
            firmware.changelog = " ".join(notes.get(version) or [])[:500] or None
        return sorted(releases.values(), key=lambda fw: self._version_key(fw.version), reverse=True)

    async def _load(self) -> Optional[Dict[str, dict]]:
        if self._catalogue is not None:
            return self._catalogue

        index = await self.fetch_page(self.INDEX_URL)
        models = self._index_models(index) if index else []
        if not models:
            return None

        catalogue: Dict[str, dict] = {}
        for model in models:
            page = await self.fetch_page(model["url"])
            versions = self._parse_model_page(page) if page else None
            if not versions:
                # A model page that fails to load or parse would drop the model silently.
                return None
            # The index can date the current release when the page does not.
            for firmware in versions:
                if firmware.version == model["version"] and firmware.release_date is None:
                    firmware.release_date = model["date"]
            catalogue[model["name"]] = {"url": model["url"], "versions": versions}

        self._catalogue = catalogue
        return catalogue

    async def fetch_device_list(self) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(success=False, error=f"Could not read Casio's firmware downloads from {self.INDEX_URL}")
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    # Pianos, keyboards, synths and the XW-PD1 groovebox: all instruments.
                    name=name,
                    category="synthesizer",
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
            return ScraperResult(success=False, error=f"Could not read Casio's firmware downloads from {self.INDEX_URL}")
        entry = catalogue.get(device_name)
        if entry is None:
            return ScraperResult(success=False, error=f"{device_name} is not in Casio's firmware downloads")
        return ScraperResult(success=True, firmware_versions=entry["versions"])
