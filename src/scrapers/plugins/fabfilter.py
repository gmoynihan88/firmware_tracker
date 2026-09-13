import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class FabFilterScraper(BaseScraper):
    """FabFilter, read from two pages: current plug-ins and previous major versions.

    **The download page states version and date together, per product**, which makes
    this one of the cleaner sources in the catalogue:

        Download FabFilter Pro-Q 4
        High-quality equalizer plug-in
        4.13 — Jun 25, 2026

    Each section also links its installers, and the filename encodes the same version
    -- `ffproq413.dmg` is 4.13, `fftimeless310.dmg` is 3.10. On 2026-09-13 all
    fourteen agreed. If they ever disagree the installer wins, because it is the file
    people actually download, and the date is dropped rather than attached to a
    version it was not written for.

    The Total bundle has a section of its own and is skipped: it is a package of the
    plug-ins below, not a product with a version.

    **Previous majors are on a second page**, and people still run them -- Pro-Q 3 is
    everywhere. Its headings run the product's major number into the version:

        Pro-Q 3.29      Pro-Q 3, final version 3.29
        Pro-L 1.37      Pro-L, final version 1.37 -- the first Pro-L had no number

    so a heading is split at the last dot, and a major of 1 gives the bare name. These
    versions are final and the page dates none of them.

    **The same page has version-shaped headings that are not plug-ins.** Under
    "Legacy Total bundle installers" sit `macOS 10.12`, `macOS 10.10 / 10.11` and
    `macOS 10.6.8 (last RTAS versions)`, which the heading pattern would read as a
    product called macOS. Only the "Legacy plug-ins" and "Discontinued plug-in
    versions" sections are read.

    The legacy page is supplementary: if it fails, the current plug-ins are still
    reported, because they are what "am I behind" is about.
    """

    manufacturer_name = "FabFilter"
    manufacturer_slug = "fabfilter"
    manufacturer_website = "https://www.fabfilter.com"

    DOWNLOAD_URL = "https://www.fabfilter.com/download"
    LEGACY_URL = "https://www.fabfilter.com/support/downloads"

    # "4.13 — Jun 25, 2026". The dash is an em dash on the page; en dash and hyphen
    # are accepted too, since that is the kind of thing a site redesign changes.
    VERSION_DATE = re.compile(
        r"(\d+\.\d+(?:\.\d+)?)\s*[—–-]\s*([A-Za-z]{3,9})\.?\s+(\d{1,2}),\s+(\d{4})"
    )
    # "/ffproq413.dmg", "/ffproq413x64.exe". The legacy bundle installers are named
    # "fftotalbundle_10.12.dmg" and deliberately do not match.
    INSTALLER = re.compile(r"/ff[a-z]+?(\d{3,4})(?:x64)?\.(?:dmg|exe)$", re.I)
    # "Pro-Q 3.29" -> ("Pro-Q", "3", "29")
    LEGACY_HEADING = re.compile(r"^(.+?)\s+(\d+)\.(\d+)$")
    LEGACY_SECTIONS = ("Legacy plug-ins", "Discontinued plug-in versions")

    MONTHS = {m: i for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun",
         "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._catalogue: Optional[Dict[str, Tuple[str, ScrapedFirmware]]] = None

    @classmethod
    def _date(cls, month: str, day: str, year: str) -> Optional[datetime]:
        number = cls.MONTHS.get(month[:3].lower())
        if number is None:
            return None
        try:
            return datetime(int(year), number, int(day))
        except ValueError:
            return None

    @classmethod
    def _installer_version(cls, hrefs: List[str]) -> Optional[str]:
        """The version an installer filename encodes: ffproq413 -> 4.13."""
        for href in hrefs:
            matched = cls.INSTALLER.search(href)
            if matched:
                digits = matched.group(1)
                return f"{digits[0]}.{digits[1:]}"
        return None

    def _parse_current(self, html: str) -> Dict[str, ScrapedFirmware]:
        soup = self.parse_html(html)
        found: Dict[str, ScrapedFirmware] = {}

        for item in soup.select("div.download-item[id^=download-]"):
            heading = item.find(["h1", "h2", "h3", "h4"])
            if heading is None:
                continue
            name = re.sub(r"^Download\s+", "", heading.get_text(" ", strip=True))
            name = re.sub(r"^FabFilter\s+", "", name).strip()
            if not name or "bundle" in name.lower():
                continue

            stated = self.VERSION_DATE.search(item.get_text(" ", strip=True))
            installer = self._installer_version(
                [a["href"] for a in item.find_all("a", href=True)]
            )

            if stated and (installer is None or installer == stated.group(1)):
                version = stated.group(1)
                release_date = self._date(*stated.groups()[1:])
            elif installer:
                if stated:
                    logger.warning(
                        "FabFilter %s: page says %s, installer is %s; using the installer",
                        name, stated.group(1), installer,
                    )
                version, release_date = installer, None
            else:
                continue

            found[name] = ScrapedFirmware(version=version, release_date=release_date)

        return found

    def _parse_legacy(self, html: str) -> Dict[str, ScrapedFirmware]:
        soup = self.parse_html(html)
        found: Dict[str, ScrapedFirmware] = {}

        for section in soup.find_all("h2"):
            if section.get_text(" ", strip=True) not in self.LEGACY_SECTIONS:
                continue
            for element in section.find_all_next(["h2", "h3"]):
                if element.name == "h2":
                    break
                matched = self.LEGACY_HEADING.match(element.get_text(" ", strip=True))
                if not matched:
                    continue
                product, major, minor = matched.groups()
                name = product if major == "1" else f"{product} {major}"
                found.setdefault(name, ScrapedFirmware(version=f"{major}.{minor}"))

        return found

    async def _load(self) -> Optional[Dict[str, Tuple[str, ScrapedFirmware]]]:
        if self._catalogue is not None:
            return self._catalogue

        html = await self.fetch_page(self.DOWNLOAD_URL)
        if not html:
            return None
        current = self._parse_current(html)
        if not current:
            return None

        catalogue: Dict[str, Tuple[str, ScrapedFirmware]] = {
            name: (self.DOWNLOAD_URL, firmware) for name, firmware in current.items()
        }

        legacy_html = await self.fetch_page(self.LEGACY_URL)
        if legacy_html:
            for name, firmware in self._parse_legacy(legacy_html).items():
                catalogue.setdefault(name, (self.LEGACY_URL, firmware))
        else:
            logger.warning("FabFilter legacy downloads page unavailable; current plug-ins only")

        self._catalogue = catalogue
        return catalogue

    async def fetch_device_list(self) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(
                success=False, error=f"No plug-in versions found at {self.DOWNLOAD_URL}"
            )
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category="vst_plugin",
                    firmware_page_url=url,
                    product_url=url,
                )
                for name, (url, _firmware) in sorted(catalogue.items())
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(
                success=False, error=f"No plug-in versions found at {self.DOWNLOAD_URL}"
            )
        entry = catalogue.get(device_name)
        if entry is None:
            # Dropped from both pages. They loaded, so this is an absence.
            return ScraperResult(success=True, firmware_versions=[])
        return ScraperResult(success=True, firmware_versions=[entry[1]])
