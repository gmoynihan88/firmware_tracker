import logging
import re
from datetime import datetime
from typing import List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class GoodhertzScraper(BaseScraper):
    """Goodhertz, whose plug-ins ship as one bundle on one version.

    `/downloads/` offers one installer for every Goodhertz plug-in -- "All the
    Goodhertz plugins in one download" -- under one heading and one date:

        <h2 class="center bundle-name">Goodhertz 3.14.1</h2>
        <h3 class="center release-date">June 30, 2026</h3>
        ... <a href="/download/Goodhertz-Installer-3.14.1-35869a1.pkg/">
        <div class="release-notes"><h3>Installation Notes</h3><ul><li>...
        <div class="release-notes"><h3>Release Notes</h3><ul><li>...

    So the catalogue has one device for the bundle, and each run records the
    current release with its date and notes. History accumulates from the first
    scrape onward; nothing older is public.

    The installer filenames carry the version too, and are preferred when they
    disagree with the heading, as the artefact rather than the prose about it. The
    date is then dropped, because it belongs to the heading's release, not the file's.

    Ruled out, 2026-09-13:
    - `/historical-artifacts`, "our full archive of past releases": a login form.
    - `/individual-downloads`, per-plug-in installers: a login form.
    - The installers themselves also need an account, so `download_url` is not set.
    """

    manufacturer_name = "Goodhertz"
    manufacturer_slug = "goodhertz"
    manufacturer_website = "https://goodhertz.com"

    DOWNLOADS_URL = "https://goodhertz.com/downloads/"
    PRODUCT_NAME = "Goodhertz Plugins"

    BUNDLE = re.compile(r"^Goodhertz\s+(\d+(?:\.\d+)+)$", re.I)
    # /download/Goodhertz-Installer-3.14.1-35869a1.exe/ -- the hash is the build, not a version.
    INSTALLER = re.compile(r"Goodhertz-Installer-(\d+(?:\.\d+)+)-[0-9a-f]+\.(?:exe|pkg|dmg|zip)", re.I)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._release: Optional[ScrapedFirmware] = None

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(part) for part in version.split("."))

    def _parse(self, html: str) -> Optional[ScrapedFirmware]:
        soup = self.parse_html(html)

        heading = soup.select_one("h2.bundle-name")
        matched = self.BUNDLE.match(" ".join(heading.get_text(" ").split())) if heading else None
        stated = matched.group(1) if matched else None

        installers = {m.group(1) for a in soup.find_all("a", href=True)
                      if (m := self.INSTALLER.search(a["href"]))}
        built = max(installers, key=self._version_key) if installers else None

        version = built or stated
        if not version:
            return None

        released = None
        if version == stated:
            date = soup.select_one("h3.release-date")
            try:
                released = datetime.strptime(" ".join(date.get_text(" ").split()), "%B %d, %Y") if date else None
            except ValueError:
                released = None
        else:
            logger.info("Goodhertz heading says %s, installers say %s; keeping the installers", stated, built)

        # Two blocks share the class: "Installation Notes" comes first, then "Release Notes".
        notes = next(
            (block.select("li") for block in soup.select("div.release-notes")
             if (title := block.find(["h2", "h3", "h4"])) and title.get_text(strip=True).lower() == "release notes"),
            [],
        )
        changelog = "\n".join("- " + " ".join(li.get_text(" ").split()) for li in notes) or None
        if version != stated:
            changelog = None  # the notes are the heading's release too

        return ScrapedFirmware(version=version, release_date=released, changelog=changelog)

    async def _load(self) -> Optional[ScrapedFirmware]:
        if self._release is None:
            html = await self.fetch_page(self.DOWNLOADS_URL)
            self._release = self._parse(html) if html else None
        return self._release

    async def fetch_device_list(self) -> ScraperResult:
        if await self._load() is None:
            return ScraperResult(success=False, error=f"No bundle version found at {self.DOWNLOADS_URL}")
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=self.PRODUCT_NAME,
                    category="vst_plugin",
                    firmware_page_url=self.DOWNLOADS_URL,
                    product_url=self.manufacturer_website,
                )
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        release = await self._load()
        if release is None:
            return ScraperResult(success=False, error=f"No bundle version found at {self.DOWNLOADS_URL}")
        if device_name != self.PRODUCT_NAME:
            return ScraperResult(success=True, firmware_versions=[])
        return ScraperResult(success=True, firmware_versions=[release])
