import re
from datetime import datetime
from typing import List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class KemperScraper(BaseScraper):
    """Kemper PROFILER, read from the downloads page and its release-notes modal.

    One product and one operating system. Kemper ships a single OS "for all PROFILER
    models" -- Head, Rack, Stage and Player -- so this is one device rather than four
    sharing a version, which is how Kemper itself presents it.

    The page is JavaScript-rendered: a plain fetch returns 189 lines with no version
    anywhere on it.

    Two sources on the one page. The download list gives the shipping release and the
    only date on offer:

        PROFILER Operating System 14.2.1 Release for all PROFILER models
        Date: 2026-08-06, File size: 30.8 MB

    and the release-notes modal behind it holds the history, 52 releases deep and
    undated:

        PROFILER Operating System 14.2.1.67566
        PROFILER Operating System 14.2.0.67476
        PROFILER Operating System 14.1.2.66277

    So the newest version carries a date and the rest do not, which is the honest
    reading -- the modal states no dates at all.

    **The list is mostly not firmware.** Of its eight entries, three are "Rig Manager
    4.2.13" for macOS, Windows and ARM64 -- the librarian application, on its own
    numbering -- two are manuals ("Addendum 14.2", "Main Manual 14.2", version-shaped
    and revisions of a document), and one is a profile pack. Only the entry naming
    the Operating System is the instrument's firmware.

    The modal states four-part versions and the list three. `14.2.1.67566` and
    `14.2.1` are the same release, so the build number is trimmed and the version
    recorded the way the download list writes it.
    """

    manufacturer_name = "Kemper"
    manufacturer_slug = "kemper"
    manufacturer_website = "https://www.kemper-amps.com"

    DOWNLOADS_URL = "https://www.kemper-amps.com/downloads"
    PRODUCT_NAME = "PROFILER"

    RENDER_WAIT = 15000

    # "PROFILER Operating System 14.2.1 Release for all PROFILER models", and in the
    # modal "PROFILER Operating System 14.2.1.67566". Anchored on the wording that
    # names the firmware, which is what separates it from Rig Manager and the manuals.
    OS_VERSION = re.compile(
        r"PROFILER\s+Operating\s+System\s+(\d+(?:\.\d+)+)", re.I
    )
    # "Date: 2026-08-06, File size: 30.8 MB"
    ENTRY_DATE = re.compile(r"Date:\s*(\d{4})-(\d{2})-(\d{2})")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._versions: Optional[List[ScrapedFirmware]] = None

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(part) for part in re.findall(r"\d+", version)) or (0,)

    @staticmethod
    def _trim_build(version: str) -> str:
        """14.2.1.67566 -> 14.2.1, which is how the download list names it."""
        parts = version.split(".")
        return ".".join(parts[:3]) if len(parts) > 3 else version

    def _parse(self, html: str) -> List[ScrapedFirmware]:
        soup = self.parse_html(html)
        found: dict = {}

        # The shipping release, and the only dated entry on the page.
        for item in soup.select("ul.downloads-list > li.panel"):
            title = item.find(["h1", "h2", "h3", "h4", "a"])
            if title is None:
                continue
            matched = self.OS_VERSION.search(title.get_text(" ", strip=True))
            if not matched:
                continue
            meta = item.select_one("span.meta")
            release_date = None
            if meta is not None:
                dated = self.ENTRY_DATE.search(meta.get_text(" ", strip=True))
                if dated:
                    try:
                        release_date = datetime(
                            int(dated.group(1)), int(dated.group(2)), int(dated.group(3))
                        )
                    except ValueError:
                        release_date = None
            version = self._trim_build(matched.group(1))
            found[version] = ScrapedFirmware(version=version, release_date=release_date)

        # The history, which the modal states without dates.
        for modal in soup.select("div.modal-content"):
            for matched in self.OS_VERSION.finditer(modal.get_text(" ", strip=True)):
                version = self._trim_build(matched.group(1))
                found.setdefault(version, ScrapedFirmware(version=version))

        return sorted(
            found.values(), key=lambda fw: self._version_key(fw.version), reverse=True
        )

    async def _load(self) -> Optional[List[ScrapedFirmware]]:
        if self._versions is not None:
            return self._versions
        html = await self.fetch_page_js(
            self.DOWNLOADS_URL, wait_for_timeout=self.RENDER_WAIT
        )
        if not html:
            return None
        versions = self._parse(html)
        if not versions:
            return None
        self._versions = versions
        return versions

    async def fetch_device_list(self) -> ScraperResult:
        versions = await self._load()
        if versions is None:
            return ScraperResult(
                success=False,
                error=f"No PROFILER operating system found at {self.DOWNLOADS_URL}",
            )

        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=self.PRODUCT_NAME,
                    category="guitar_pedal",
                    firmware_page_url=self.DOWNLOADS_URL,
                    product_url=self.DOWNLOADS_URL,
                )
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        versions = await self._load()
        if versions is None:
            return ScraperResult(
                success=False,
                error=f"No PROFILER operating system found at {self.DOWNLOADS_URL}",
            )
        if device_name != self.PRODUCT_NAME:
            return ScraperResult(success=True, firmware_versions=[])
        return ScraperResult(success=True, firmware_versions=versions)
