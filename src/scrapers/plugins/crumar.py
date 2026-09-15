import re
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class CrumarScraper(BaseScraper):
    """Crumar keyboards, read from the firmware downloads on each support page.

    The support index (`/?a=support`) links one page per product, and each page is a
    table of that product's downloads:

        <a href="/?a=dl&b=140"
           title=" Crumar_Mojo61_Update_v1.53.zip - November 27, 2024 ">
          Mojo 61 - Firmware Update v.1.53</a>

    The version is in the file name and the link text, and the `title` carries the
    date the file was posted. Only the current file is offered, so each product has
    one version, not a history.

    **Every page repeats a set of shared downloads** under the product's own: eleven
    sample expansions, "Crumar Midi USB multi-client Windows driver v.2.0.0.0" and the
    EULA. The driver's version is not any keyboard's firmware, and neither is "Mojo 61
    - Piano Update", a sample set. A link counts only when its text says Firmware.

    **The catalogue is the products with a firmware link**: Seven, Mojo 61, Mojo
    Classic/Suitcase, Sorrento and DK61 on 2026-09-15. Eleven, Seventeen, Parsifal,
    MojoPedals and Burn offer manuals only, and Performer is a plug-in whose installers
    are not firmware. Listing those would add rows that report nothing on every run.

    Until 2026-09-15 this scraper read a hand-kept list of four from product pages
    that no longer exist (`/seven/`, `/mojo-61/`), and found nothing for any of them.
    D9-X, a GMLAB board with no version published anywhere, had an unverified value
    labelled as such; Mojo Desktop has no support page. Neither is on the index, so
    both left the listing and keep their rows.
    """

    manufacturer_name = "Crumar"
    manufacturer_slug = "crumar"
    manufacturer_website = "https://www.crumar.it"

    SUPPORT_INDEX = "https://www.crumar.it/?a=support"
    SUPPORT_LINK = re.compile(r"[?&]a=support&b=(\d+)")
    DOWNLOAD_LINK = re.compile(r"[?&]a=dl&b=\d+")

    # The index's name -> the database's.
    RENAMES = {"MOJO61": "Mojo 61"}

    # " Crumar_Mojo61_Update_v1.53.zip - November 27, 2024 "
    TITLE = re.compile(
        r"^\s*(?P<file>\S.*?)\s+-\s+(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})\s*$"
    )
    MONTHS = {m: i for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun",
         "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

    # The file name is the artefact, so its version wins -- but only when it is
    # dotted. DK61's file is "Crumar_DK61_Updater_V101.zip", which says 1.0.1 only
    # to someone who already knows; its link text, "Firmware updater v.1.0.1", does
    # not need decoding.
    FILE_VERSION = re.compile(r"[Vv]\.?(\d+(?:\.\d+)+)(?=\D*$)")
    # "Firmware Update v.1.53", "Firmware v.1.37", "Firmware 1.13", "Firmware updater v.1.0.1"
    TEXT_VERSION = re.compile(r"\bFirmware\b.*?\b[Vv]?\.?\s*(\d+(?:\.\d+)+)\s*$", re.I)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._catalogue: Optional[Dict[str, dict]] = None

    def _parse_index(self, html: str) -> Dict[str, str]:
        """Product name -> support page, in the index's order."""
        pages: Dict[str, str] = {}
        for anchor in self.parse_html(html).find_all("a", href=self.SUPPORT_LINK):
            name = anchor.get_text(" ", strip=True)
            if name:
                pages.setdefault(self.RENAMES.get(name, name), urljoin(self.SUPPORT_INDEX, anchor["href"]))
        return pages

    def _release_date(self, match) -> Optional[datetime]:
        try:
            return datetime(
                int(match.group("year")),
                self.MONTHS[match.group("month")[:3].lower()],
                int(match.group("day")),
            )
        except (ValueError, KeyError):
            return None

    def _parse_firmware(self, html: str) -> List[ScrapedFirmware]:
        """The firmware download on one support page, if it offers one."""
        versions: List[ScrapedFirmware] = []
        seen = set()

        for anchor in self.parse_html(html).find_all("a", href=self.DOWNLOAD_LINK):
            text = anchor.get_text(" ", strip=True)
            text_version = self.TEXT_VERSION.search(text)
            if not text_version:
                continue

            title = self.TITLE.match(anchor.get("title") or "")
            file_version = self.FILE_VERSION.search(title.group("file")) if title else None
            version = file_version.group(1) if file_version else text_version.group(1)
            if version in seen:
                continue
            seen.add(version)

            versions.append(
                ScrapedFirmware(
                    version=version,
                    release_date=self._release_date(title) if title else None,
                    download_url=urljoin(self.manufacturer_website, anchor["href"]),
                    changelog=text,
                )
            )

        return versions

    async def _load(self) -> Optional[Dict[str, dict]]:
        """Every product with a firmware download, read once per scrape."""
        if self._catalogue is not None:
            return self._catalogue

        index = await self.fetch_page(self.SUPPORT_INDEX)
        if not index:
            return None
        pages = self._parse_index(index)
        if not pages:
            return None

        catalogue: Dict[str, dict] = {}
        for name, url in pages.items():
            html = await self.fetch_page(url)
            if not html:
                # A page that fails to load would silently drop its product from the
                # catalogue, which is indistinguishable from one with no firmware.
                return None
            firmware = self._parse_firmware(html)
            if firmware:
                catalogue[name] = {"url": url, "firmware": firmware}

        self._catalogue = catalogue
        return catalogue

    async def fetch_device_list(self) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(
                success=False,
                error=f"Could not read Crumar's support pages from {self.SUPPORT_INDEX}",
            )

        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    # Everything Crumar publishes firmware for is a keyboard.
                    name=name,
                    category="synthesizer",
                    firmware_page_url=entry["url"],
                    product_url=entry["url"].replace("a=support", "a=showproduct"),
                )
                for name, entry in catalogue.items()
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(
                success=False,
                error=f"Could not read Crumar's support pages from {self.SUPPORT_INDEX}",
            )

        entry = catalogue.get(device_name)
        # D9-X and Mojo Desktop keep rows from before the list came from the index,
        # and Crumar offers no firmware download for either.
        return ScraperResult(success=True, firmware_versions=entry["firmware"] if entry else [])
