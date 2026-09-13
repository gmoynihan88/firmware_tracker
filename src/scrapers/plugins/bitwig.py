import re
from datetime import datetime
from typing import List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class BitwigScraper(BaseScraper):
    """Bitwig Studio, read from the release archive as a plain table.

    One product, 146 releases, **every one dated**, from a single fetch. The
    archive is an ordinary HTML table -- version, date, a download per platform,
    a link to the release notes:

        6.1.1    Sep 2, 2026    Windows  Windows (ARM)  macOS  Flatpak  Ubuntu
        6.1      Aug 26, 2026   Windows  Windows (ARM)  macOS  Flatpak  Ubuntu

    **This vendor was written off as gated and was not.** The earlier reading was
    that `/previous_releases/` "renders a login", which it does -- in the site
    header, on every page including the ones that work. The table is served to a
    plain `fetch_page` with no session, no browser and no key. A login form in
    the chrome is not a gate, and the way to tell is that the page also contains
    a version list.

    **Two tables, one product.** Bitwig splits the archive into Bitwig Studio
    (2.0 through 6.1.1) and Bitwig Studio 1 (1.0 through 1.3.16) because the
    installers differ, not because they are separate products, so both are read
    into one device. That is the opposite of Ableton, which is split into Live 11
    and Live 12 here because Ableton maintains both lines in parallel and each
    has its own release-notes page. Bitwig has one line: 6.1.1 succeeds 6.1
    succeeds 6.0.11, and nothing is backported.

    **Versions must sort numerically.** 146 releases mean two-digit patch numbers,
    and as strings `6.0.6` sorts above `6.0.11`, which would report a release from
    April as newer than one from June.

    Bitwig Connect, the audio interface, is absent deliberately: its product page,
    the support page and the download page mention firmware exactly zero times, so
    there is nothing to track rather than a blank row to explain.

    Each row links a download per platform -- Windows, Windows ARM, macOS, Flatpak,
    Ubuntu -- and choosing one of them to store as *the* download URL would be
    arbitrary, so none is stored.
    """

    manufacturer_name = "Bitwig"
    manufacturer_slug = "bitwig"
    manufacturer_website = "https://www.bitwig.com"

    RELEASES_URL = "https://www.bitwig.com/previous_releases/"
    PRODUCT_NAME = "Bitwig Studio"

    # A version cell holds nothing else: "6.1.1", "6.1", "1.0.3".
    VERSION_CELL = re.compile(r"^(\d+(?:\.\d+)+)$")
    # "Sep 2, 2026". Matched by name rather than handed to strptime, which rejects
    # the four-letter "Sept" that other vendors here write.
    DATE_CELL = re.compile(r"^([A-Za-z]{3,9})\s+(\d{1,2}),\s+(\d{4})$")
    MONTHS = {month: index for index, month in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun",
         "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._versions: Optional[List[ScrapedFirmware]] = None

    @staticmethod
    def _version_key(version: str) -> tuple:
        """6.0.11 is newer than 6.0.6, which a string comparison gets backwards."""
        return tuple(int(part) for part in version.split("."))

    @classmethod
    def _parse_date(cls, text: str) -> Optional[datetime]:
        matched = cls.DATE_CELL.match(text)
        if not matched:
            return None
        month = cls.MONTHS.get(matched.group(1)[:3].lower())
        if month is None:
            return None
        try:
            return datetime(int(matched.group(3)), month, int(matched.group(2)))
        except ValueError:
            return None

    def _parse(self, html: str) -> List[ScrapedFirmware]:
        soup = self.parse_html(html)
        found: dict = {}

        # Both tables, because both are Bitwig Studio.
        for row in soup.find_all("tr"):
            cells = [cell.get_text(" ", strip=True)
                     for cell in row.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            matched = self.VERSION_CELL.match(cells[0])
            if not matched:
                continue
            found.setdefault(
                matched.group(1),
                ScrapedFirmware(
                    version=matched.group(1),
                    release_date=self._parse_date(cells[1]),
                ),
            )

        return sorted(
            found.values(), key=lambda fw: self._version_key(fw.version), reverse=True
        )

    async def _load(self) -> Optional[List[ScrapedFirmware]]:
        if self._versions is not None:
            return self._versions
        html = await self.fetch_page(self.RELEASES_URL)
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
                success=False, error=f"No releases found at {self.RELEASES_URL}"
            )

        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=self.PRODUCT_NAME,
                    category="vst_plugin",
                    firmware_page_url=self.RELEASES_URL,
                    product_url="https://www.bitwig.com/download/",
                )
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        versions = await self._load()
        if versions is None:
            return ScraperResult(
                success=False, error=f"No releases found at {self.RELEASES_URL}"
            )
        if device_name != self.PRODUCT_NAME:
            return ScraperResult(success=True, firmware_versions=[])
        return ScraperResult(success=True, firmware_versions=versions)
