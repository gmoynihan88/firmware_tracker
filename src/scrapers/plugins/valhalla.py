import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class ValhallaDSPScraper(BaseScraper):
    """Valhalla DSP, read from the demos-and-downloads page that covers the range.

    One fetch, ten plug-ins. Each has a Mac and a Windows download, and each download
    is a small form whose hidden inputs say what it is:

        plugin_slug   shimmer
        plugin_name   Valhalla Shimmer Demo
        demo_name     Version 1.3.0 Updated 1/30/2023
        download_url  .../ValhallaShimmerOSXDemo_1_3_0.dmg

    The demo installers carry the same version the product pages call current -- all
    ten matched on 2026-09-13 -- so the demo page stands for the product.

    **The Windows builds lag, for five of the ten.** Shimmer is 1.3.0 on Mac and
    1.2.2 on Windows; Plate 1.6.8 and 1.6.3; UberMod 1.2.8 and 1.1.6; Freq Echo 1.2.8
    and 1.2.0; Space Modulator 1.2.8 and 1.1.6. A device has one version here, so the
    newest build is recorded, with that build's own date. This app's plug-in scanner
    runs on macOS, which is the platform that gets the newest builds; a Windows user
    would be told about an update Valhalla has not shipped for Windows.

    **The label is written several ways**, all on the one page:

        Version 1.0.2: Updated 11/22/2025      month/day/year
        Version 1.3.0 Updated 1/30/2023        no colon
        Version 1.2.2: Updated 10/07/20        two-digit year
        Latest: Version 1.2.8                  free plug-ins, no date at all

    **The installer filename is checked against the label**, and wins if they
    disagree, dropping the date. Filenames carry build suffixes the version must not
    absorb: `ValhallaShimmerDemoWin_V1_2_2v2.zip` is 1.2.2 and
    `ValhallaPlateDemoWin_1_6_3b3.zip` is 1.6.3.

    Names come from `plugin_name` with "Demo" removed. This page spells one product
    "Ubermod" where its own product page says "UberMod", so that one is aliased.
    """

    manufacturer_name = "Valhalla DSP"
    manufacturer_slug = "valhalla"
    manufacturer_website = "https://valhalladsp.com"

    DOWNLOADS_URL = "https://valhalladsp.com/demos-downloads/"

    LABEL = re.compile(
        r"Version\s+(\d+(?:\.\d+)+)\s*:?\s*(?:Updated\s+(\d{1,2})/(\d{1,2})/(\d{2,4}))?",
        re.I,
    )
    FILE_VERSION = re.compile(
        r"_V?(\d+)_(\d+)_(\d+)(?:[a-z]+\d*)?\.(?:dmg|zip|pkg|exe)$", re.I
    )
    # Where this page's spelling differs from the product's own page.
    NAMES = {"ubermod": "Valhalla UberMod"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._catalogue: Optional[Dict[str, ScrapedFirmware]] = None

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(part) for part in version.split("."))

    @staticmethod
    def _date(month: str, day: str, year: str) -> Optional[datetime]:
        full_year = int(year) + 2000 if len(year) == 2 else int(year)
        try:
            return datetime(full_year, int(month), int(day))
        except ValueError:
            return None

    def _read_build(self, label: str, url: str) -> Optional[ScrapedFirmware]:
        stated = self.LABEL.search(label)
        in_file = self.FILE_VERSION.search(url.rsplit("/", 1)[-1])
        file_version = ".".join(in_file.groups()) if in_file else None

        if stated and (file_version is None or file_version == stated.group(1)):
            release_date = self._date(*stated.groups()[1:]) if stated.group(2) else None
            return ScrapedFirmware(version=stated.group(1), release_date=release_date)
        if file_version:
            if stated:
                logger.warning(
                    "Valhalla: label says %s, installer %s is %s; using the installer",
                    stated.group(1), url.rsplit("/", 1)[-1], file_version,
                )
            return ScrapedFirmware(version=file_version)
        return None

    def _parse(self, html: str) -> Dict[str, ScrapedFirmware]:
        soup = self.parse_html(html)
        builds: Dict[str, List[Tuple[str, ScrapedFirmware]]] = {}

        for form in soup.select("form.demo-download-form"):
            def value(name: str) -> str:
                field = form.find("input", attrs={"name": name})
                return field.get("value", "") if field else ""

            slug = value("plugin_slug").strip()
            name = self.NAMES.get(slug) or re.sub(r"\s+Demo$", "", value("plugin_name").strip())
            if not slug or not name:
                continue
            build = self._read_build(value("demo_name"), value("download_url"))
            if build is not None:
                builds.setdefault(slug, []).append((name, build))

        found: Dict[str, ScrapedFirmware] = {}
        for entries in builds.values():
            name, newest = max(entries, key=lambda entry: self._version_key(entry[1].version))
            found[name] = newest
        return found

    async def _load(self) -> Optional[Dict[str, ScrapedFirmware]]:
        if self._catalogue is not None:
            return self._catalogue
        html = await self.fetch_page(self.DOWNLOADS_URL)
        if not html:
            return None
        catalogue = self._parse(html)
        if not catalogue:
            return None
        self._catalogue = catalogue
        return catalogue

    async def fetch_device_list(self) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(
                success=False, error=f"No plug-in downloads found at {self.DOWNLOADS_URL}"
            )
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category="vst_plugin",
                    firmware_page_url=self.DOWNLOADS_URL,
                    product_url=self.DOWNLOADS_URL,
                )
                for name in sorted(catalogue)
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(
                success=False, error=f"No plug-in downloads found at {self.DOWNLOADS_URL}"
            )
        firmware = catalogue.get(device_name)
        if firmware is None:
            return ScraperResult(success=True, firmware_versions=[])
        return ScraperResult(success=True, firmware_versions=[firmware])
