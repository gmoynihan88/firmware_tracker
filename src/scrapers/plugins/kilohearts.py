import logging
import re
from datetime import datetime
from typing import List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)

MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]


class KiloheartsScraper(BaseScraper):
    """Kilohearts, whose plug-ins ship and update as one suite.

    Every Kilohearts plug-in -- Phase Plant, Multipass, Snap Heap and the snapins --
    installs from one Kilohearts Installer and shares one version number, so the
    catalogue has one device for the suite rather than the same history copied onto
    every plug-in. The changelog says so in its own title, "Kilohearts Plugins
    Changelog", and files each release's notes under the plug-ins it touched.

    `/changelog` is one page of 82 releases back to 1.5.0 in November 2018, every one
    dated, each a section whose heading holds both version and date:

        <section id="2.4.5"><h3><a>2.4.5</a> <span> - December 11, 2025</span></h3>
          <h4>Phase Plant</h4> ... <h4>General</h4> ...

    Only those headings are read. The `h4`s inside a release name plug-ins and
    platforms, and the notes under them mention version-shaped things of their own.

    `/download` states the installer's current version -- "Kilohearts Installer /
    2.4.6 for Mac" -- which matched the changelog on 2026-09-13. If it is ever ahead,
    it is added as the latest version, undated: the same check u-he's release notes
    needed. The download page failing costs that check, not the changelog.
    """

    manufacturer_name = "Kilohearts"
    manufacturer_slug = "kilohearts"
    manufacturer_website = "https://kilohearts.com"

    CHANGELOG_URL = "https://kilohearts.com/changelog"
    DOWNLOAD_URL = "https://kilohearts.com/download"
    PRODUCT_NAME = "Kilohearts Plugins"

    # "2.4.5 - December 11, 2025", with any dash a redesign might substitute.
    HEADING = re.compile(r"^(\d+(?:\.\d+)+)\s*[-–—]\s*([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})$")
    # "2.4.6 for Mac", "2.4.6 for Windows"
    INSTALLER = re.compile(r"(\d+(?:\.\d+)+)\s+for\s+(?:Mac|Windows|Linux)\b", re.I)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._versions: Optional[List[ScrapedFirmware]] = None

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(part) for part in version.split("."))

    def _parse_changelog(self, html: str) -> List[ScrapedFirmware]:
        soup = self.parse_html(html)
        headings = [section.find("h3") for section in soup.select("section[id]")] or soup.find_all("h3")
        versions: List[ScrapedFirmware] = []
        seen = set()
        for heading in headings:
            if heading is None:
                continue
            matched = self.HEADING.match(" ".join(heading.get_text(" ", strip=True).split()))
            if not matched or matched.group(1) in seen:
                continue
            version, month, day, year = matched.groups()
            seen.add(version)
            try:
                released = datetime(int(year), MONTHS.index(month.lower()) + 1, int(day))
            except ValueError:
                released = None
            versions.append(ScrapedFirmware(version=version, release_date=released))
        return versions

    def _installer_version(self, html: str) -> Optional[str]:
        text = " ".join(self.parse_html(html).get_text(" ").split())
        found = [m.group(1) for m in self.INSTALLER.finditer(text)]
        return max(found, key=self._version_key) if found else None

    async def _load(self) -> Optional[List[ScrapedFirmware]]:
        if self._versions is not None:
            return self._versions

        page = await self.fetch_page(self.CHANGELOG_URL)
        if not page:
            return None
        versions = self._parse_changelog(page)
        if not versions:
            return None

        download = await self.fetch_page(self.DOWNLOAD_URL)
        installer = self._installer_version(download) if download else None
        known = {fw.version for fw in versions}
        if installer and installer not in known and \
                self._version_key(installer) > max(self._version_key(v) for v in known):
            logger.info("Kilohearts installer %s is newer than the changelog", installer)
            versions.append(ScrapedFirmware(version=installer))

        versions.sort(key=lambda fw: self._version_key(fw.version), reverse=True)
        self._versions = versions
        return versions

    async def fetch_device_list(self) -> ScraperResult:
        versions = await self._load()
        if versions is None:
            return ScraperResult(success=False, error=f"No releases found at {self.CHANGELOG_URL}")
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=self.PRODUCT_NAME,
                    category="vst_plugin",
                    firmware_page_url=self.CHANGELOG_URL,
                    product_url=self.DOWNLOAD_URL,
                )
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        versions = await self._load()
        if versions is None:
            return ScraperResult(success=False, error=f"No releases found at {self.CHANGELOG_URL}")
        if device_name != self.PRODUCT_NAME:
            return ScraperResult(success=True, firmware_versions=[])
        return ScraperResult(success=True, firmware_versions=list(versions))
