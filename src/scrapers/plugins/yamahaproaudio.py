import re
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class YamahaProAudioScraper(BaseScraper):
    """Yamaha's digital mixing consoles and their Dante I/O, from the mixers' downloads pages.

    The mixers index (usa.yamaha.com/products/proaudio/mixers/) links each family, and
    each family's downloads page lists its firmware twice over: a table of current
    downloads with a Last Update column, and collapsible "previous versions" sections.
    Seven families carry firmware on 2026-09-15 -- CL, QL, TF, TF-RACK, DM3, DM7 and
    RIVAGE PM -- and the analogue EMX and MG families list none. robots.txt sets rules
    only for other crawlers. A separate manufacturer from "Yamaha" (the music production
    scraper), because names are unique.

        <tr><td><a href="/support/updates/cl1_firm.html">CL1 Firmware V5.91</a></td><td>-</td><td>20.6MB</td><td>2026-02-12</td></tr>
        <section class="previous_ver_heading"><h3 class="heading">TF5/3/1 TF-RACK Firmware</h3>
          <ul><li><a href="/support/updates/tf531_tf_rack_firm_v455.html">TF5/3/1 TF-RACK Firmware V4.55</a></li>...

    **Only links naming Firmware are read.** The same pages list CL Editor, TF Editor,
    Dante Controller and other applications with versions of their own.

    **A current row is dated from its Last Update column**, as the music production
    scraper does; previous versions are listed without dates and stay undated. The
    firmware detail pages add no date of their own -- their only date is the licence's
    "Last updated: July 10, 2024".

    **A previous version belongs to its section's line, not its link's wording.** The
    TF5/3/1 TF-RACK section lists "TF Firmware V2.50-2" back to V1.10, the line's name
    before TF-RACK joined it, so those are TF5, TF3, TF1 and TF-RACK history.

    **Lines name several models.** "TF5/3/1 TF-RACK" is TF5, TF3, TF1 and TF-RACK;
    "Tio1608-D2, Tio1608-D" is both units. The Dante I/O racks appear on several
    families' pages and are read once.

    **Versions are written as Yamaha does**: "V3.51-2" is a re-release, and the HY144-D
    card's "V4.2.3.1_3.1.1" pairs its Dante and card firmware. Two downloads of one
    version -- RMio64-D's "for updating with R-Remote" and "for updating with RMio64-D
    Update Program", TF's "(from V1.61 and older)" -- are one release.
    """

    manufacturer_name = "Yamaha Pro Audio"
    manufacturer_slug = "yamahaproaudio"
    manufacturer_website = "https://usa.yamaha.com"

    SITE = "https://usa.yamaha.com"
    MIXERS_INDEX = "https://usa.yamaha.com/products/proaudio/mixers/"

    FAMILY_LINK = re.compile(r"^(?:https://usa\.yamaha\.com)?/products/proaudio/mixers/(?P<family>[a-z0-9_+-]+)/index\.html$")
    FIRMWARE = re.compile(
        r"^(?P<line>.+?)\s+Firmware\s+V(?P<version>\d+(?:\.\d+)+(?:-\d+)?(?:_\d+(?:\.\d+)+)?)(?![\d.])", re.I
    )
    SECTION_HEADING = re.compile(r"^(?P<line>.+?)\s+Firmware$", re.I)
    NUMBERED = re.compile(r"^(?P<prefix>[A-Za-z][A-Za-z-]*?)(?P<first>\d+)(?P<more>(?:/\d+)+)$")
    DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._catalogue: Optional[Dict[str, dict]] = None

    @staticmethod
    def _text(element) -> str:
        return " ".join(element.get_text(" ", strip=True).split())

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(part) for part in re.findall(r"\d+", version))

    def _models(self, line: str) -> List[str]:
        """"TF5/3/1 TF-RACK" -> TF5, TF3, TF1, TF-RACK; "Tio1608-D2, Tio1608-D" -> both."""
        models: List[str] = []
        for part in re.split(r",\s*", line.strip()):
            tokens = part.split(" ")
            numbered = self.NUMBERED.match(tokens[0])
            if numbered:
                numbers = [numbered.group("first")] + numbered.group("more").strip("/").split("/")
                models += [numbered.group("prefix") + number for number in numbers]
                if len(tokens) > 1:
                    models.append(" ".join(tokens[1:]))
            elif part:
                models.append(part)
        return models

    def _add(self, found: Dict[str, dict], models: List[str], firmware: ScrapedFirmware, page_url: str, current: bool):
        for model in models:
            entry = found.setdefault(model, {"url": None, "downloads": page_url, "versions": {}})
            known = entry["versions"].get(firmware.version)
            if known is None or (firmware.release_date and not known.release_date):
                entry["versions"][firmware.version] = firmware
            if current and entry["url"] is None:
                entry["url"] = firmware.download_url

    def _parse_downloads(self, html: str, page_url: str, found: Dict[str, dict]) -> None:
        soup = self.parse_html(html)

        for row in soup.find_all("tr"):
            link = row.find("a", href=True)
            matched = self.FIRMWARE.match(self._text(link)) if link else None
            if not matched:
                continue
            stamp = next((text for text in (self._text(cell) for cell in row.find_all("td")) if self.DATE.fullmatch(text)), None)
            firmware = ScrapedFirmware(
                version=matched.group("version"),
                release_date=datetime.strptime(stamp, "%Y-%m-%d") if stamp else None,
                download_url=urljoin(self.SITE, link["href"]),
            )
            self._add(found, self._models(matched.group("line")), firmware, page_url, current=True)

        for heading in soup.select("section h3"):
            section_line = self.SECTION_HEADING.match(self._text(heading))
            if not section_line:
                continue
            models = self._models(section_line.group("line"))
            for link in heading.find_parent("section").select("ul a[href]"):
                matched = self.FIRMWARE.match(self._text(link))
                if matched:
                    firmware = ScrapedFirmware(
                        version=matched.group("version"), release_date=None, download_url=urljoin(self.SITE, link["href"])
                    )
                    self._add(found, models, firmware, page_url, current=False)

    async def _load(self) -> Optional[Dict[str, dict]]:
        if self._catalogue is not None:
            return self._catalogue

        index = await self.fetch_page(self.MIXERS_INDEX)
        if not index:
            return None
        families: List[str] = []
        for anchor in self.parse_html(index).find_all("a", href=True):
            matched = self.FAMILY_LINK.match(anchor["href"])
            if matched and matched.group("family") not in families:
                families.append(matched.group("family"))
        if not families:
            return None

        found: Dict[str, dict] = {}
        for family in families:
            page_url = f"{self.SITE}/products/proaudio/mixers/{family}/downloads.html"
            html = await self.fetch_page(page_url)
            if not html:
                # A family whose downloads page fails would drop its consoles silently.
                return None
            self._parse_downloads(html, page_url, found)

        catalogue = {
            model: {
                "url": entry["url"] or entry["downloads"],
                "downloads": entry["downloads"],
                "versions": sorted(entry["versions"].values(), key=lambda fw: self._version_key(fw.version), reverse=True),
            }
            for model, entry in found.items()
        }
        if not catalogue:
            return None
        self._catalogue = catalogue
        return catalogue

    async def fetch_device_list(self) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(success=False, error=f"Could not read Yamaha's mixer downloads from {self.MIXERS_INDEX}")
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    # Consoles, stage boxes and cards: none of the other categories fits.
                    name=model,
                    category="other",
                    firmware_page_url=entry["url"],
                    product_url=entry["downloads"],
                )
                for model, entry in catalogue.items()
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(success=False, error=f"Could not read Yamaha's mixer downloads from {self.MIXERS_INDEX}")
        entry = catalogue.get(device_name)
        if entry is None:
            return ScraperResult(success=False, error=f"No firmware for {device_name} on Yamaha's mixer downloads pages")
        return ScraperResult(success=True, firmware_versions=entry["versions"])
