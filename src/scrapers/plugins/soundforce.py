import re
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class SoundForceScraper(BaseScraper):
    """Scraper for Sound-Force MIDI controllers.

    Update pages are resolved from the Support page on every scrape rather than
    hardcoded. The previous URLs were WordPress ?page_id= values, two of which had
    changed: SFC-5's page is 5145 rather than 4617, and SFC-Mini's is 5110 rather
    than 5050. Both dead ids returned an identical 1037-character "Page Not Found".

    Sound-Force has since moved two products' notes onto a Notion site, which the
    Support page links to alongside the rest.

    The controllers themselves come from the same links. They were a hand-kept list
    of six until 2026-09-15, which matched the page exactly -- so nothing was being
    missed yet, but a seventh controller would have been.
    """

    manufacturer_name = "Sound-Force"
    manufacturer_slug = "soundforce"
    manufacturer_website = "https://sound-force.nl"

    SUPPORT_URL = "https://sound-force.nl/support/"

    # WordPress pages write "V1.11:"; the Notion pages prefix a date,
    # "25/11/2025: V1.9:". One pattern covers both.
    RELEASE = re.compile(
        r"^(?:(\d{2})/(\d{2})/(\d{4}):\s*)?[Vv](\d+(?:\.\d+)+):"
    )

    # Some entries put the date on its own line above the version, behind a dash:
    #
    #     - 18/07/2022:
    #     V1.10:
    #     MacOS updater app download
    #
    # The combined pattern above only matches when both share a line, so those
    # releases were parsed with no date at all -- the date was sitting one line up.
    DATE_LINE = re.compile(r"^[\u2013\u2014-]?\s*(\d{2})/(\d{2})/(\d{4}):?\s*$")

    # The Support page links one "<controller> updates" page per controller, current
    # and legacy alike, and that list is the catalogue: a controller Sound-Force adds
    # is picked up from its link.
    UPDATES_LINK = re.compile(r"^(?P<name>.+?)\s+updates$", re.I)

    # Sound-Force titles its pages by hardware revision -- "SFC-60 V3 updates" -- and
    # these three were catalogued without it. Adopting the page's names would orphan
    # the rows users' devices are attached to. Not a rule for stripping revisions:
    # "SFC-Mini V4" is a different controller from "SFC-Mini" and keeps its V4.
    RENAMES = {
        "SFC-60 V3": "SFC-60",
        "SFC-5 V2": "SFC-5",
        "SFC-Mini V3": "SFC-Mini",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._update_pages: Optional[Dict[str, str]] = None

    def _parse_update_links(self, html: str) -> Dict[str, str]:
        """Controller name -> its update page, in the Support page's order."""
        links: Dict[str, str] = {}
        for anchor in self.parse_html(html).find_all("a", href=True):
            match = self.UPDATES_LINK.match(anchor.get_text(" ", strip=True))
            if not match:
                continue
            name = self.RENAMES.get(match.group("name"), match.group("name"))
            links.setdefault(name, urljoin(self.SUPPORT_URL, anchor["href"]))
        return links

    async def _get_update_pages(self) -> Optional[Dict[str, str]]:
        """The Support page's update links, fetched once per scrape."""
        if self._update_pages is not None:
            return self._update_pages

        html = await self.fetch_page_js(self.SUPPORT_URL, wait_for_timeout=25000)
        if not html:
            return None

        links = self._parse_update_links(html)
        if not links:
            return None

        self._update_pages = links
        return self._update_pages

    def _parse_updates(self, html: str) -> List[ScrapedFirmware]:
        """Read the release list from an update page.

        Each version appears twice, once for the macOS updater and once for Windows,
        so entries are de-duplicated on the version itself.
        """
        versions: List[ScrapedFirmware] = []
        seen = set()
        # The most recent date seen above the current line. A version carrying its own
        # date still wins; this only fills in the split layout. It is deliberately not
        # cleared after use, because one date heads both the macOS and Windows entries.
        pending: Optional[tuple] = None

        for raw in self.parse_html(html).get_text("\n").splitlines():
            line = raw.strip()

            standalone = self.DATE_LINE.match(line)
            if standalone:
                pending = standalone.groups()
                continue

            match = self.RELEASE.match(line)
            if not match:
                continue

            day, month, year, version = match.groups()
            if not (day and month and year) and pending:
                day, month, year = pending

            if version in seen:
                continue

            release_date = None
            if day and month and year:
                try:
                    release_date = datetime(int(year), int(month), int(day))
                except ValueError:
                    release_date = None

            seen.add(version)
            versions.append(ScrapedFirmware(version=version, release_date=release_date))

        return sorted(
            versions,
            key=lambda fw: tuple(int(p) for p in re.findall(r"\d+", fw.version)),
            reverse=True,
        )

    async def fetch_device_list(self) -> ScraperResult:
        pages = await self._get_update_pages()
        if pages is None:
            return ScraperResult(
                success=False,
                error=f"No update pages linked from the Sound-Force support page at {self.SUPPORT_URL}",
            )

        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    # Sound-Force makes nothing but MIDI controllers.
                    name=name,
                    category="midi_controller",
                    firmware_page_url=url,
                    product_url=self.SUPPORT_URL,
                )
                for name, url in pages.items()
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        html = await self.fetch_page_js(firmware_page_url, wait_for_timeout=25000)
        if not html:
            return ScraperResult(
                success=False, error=f"Failed to fetch {firmware_page_url}"
            )

        versions = self._parse_updates(html)
        if not versions:
            return ScraperResult(
                success=False,
                error=f"No versions found for {device_name} at {firmware_page_url}",
            )

        return ScraperResult(success=True, firmware_versions=versions)
