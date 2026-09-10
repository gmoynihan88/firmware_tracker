import re
from datetime import datetime
from typing import Dict, List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class SoundForceScraper(BaseScraper):
    """Scraper for Sound-Force MIDI controllers.

    Update pages are resolved from the Support page on every scrape rather than
    hardcoded. The previous URLs were WordPress ?page_id= values, two of which had
    changed: SFC-5's page is 5145 rather than 4617, and SFC-Mini's is 5110 rather
    than 5050. Both dead ids returned an identical 1037-character "Page Not Found".

    Sound-Force has since moved two products' notes onto a Notion site, which the
    Support page links to alongside the rest.
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

    # (device name, category, the Support page's link text)
    # Device names are kept as they already exist in the database. Sound-Force titles
    # its pages by hardware revision -- "SFC-60 V3 updates" -- and adopting those
    # names wholesale would orphan the rows users' devices are attached to.
    PRODUCTS = [
        ("SFC-60", "midi_controller", "SFC-60 V3 updates"),
        ("SFC-5", "midi_controller", "SFC-5 V2 updates"),
        ("SFC-Mini", "midi_controller", "SFC-Mini V3 updates"),
        ("SFC-Mini V4", "midi_controller", "SFC-Mini V4 updates"),
        ("SFC-OB", "midi_controller", "SFC-OB updates"),
        ("SFC-8", "midi_controller", "SFC-8 updates"),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._update_pages: Optional[Dict[str, str]] = None

    async def _get_update_pages(self) -> Optional[Dict[str, str]]:
        """Map each Support page link to its update page, fetched once per scrape."""
        if self._update_pages is not None:
            return self._update_pages

        html = await self.fetch_page_js(self.SUPPORT_URL, wait_for_timeout=25000)
        if not html:
            return None

        soup = self.parse_html(html)
        links = {}
        for anchor in soup.find_all("a", href=True):
            text = anchor.get_text(strip=True)
            if text.lower().endswith("updates"):
                links[text] = anchor["href"]

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

        for line in self.parse_html(html).get_text("\n").splitlines():
            match = self.RELEASE.match(line.strip())
            if not match:
                continue

            day, month, year, version = match.groups()
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
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category=category,
                    firmware_page_url=self.SUPPORT_URL,
                    product_url=self.SUPPORT_URL,
                )
                for name, category, _link in self.PRODUCTS
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        pages = await self._get_update_pages()
        if pages is None:
            return ScraperResult(
                success=False,
                error=f"Could not read the Sound-Force support page at {self.SUPPORT_URL}",
            )

        link_text = next(
            (link for name, _c, link in self.PRODUCTS if name == device_name), None
        )
        if not link_text or link_text not in pages:
            return ScraperResult(
                success=False,
                error=(
                    f"No update page linked for {device_name} "
                    f"(looked for {link_text!r} on the support page)"
                ),
            )

        html = await self.fetch_page_js(pages[link_text], wait_for_timeout=25000)
        if not html:
            return ScraperResult(
                success=False, error=f"Failed to fetch {pages[link_text]}"
            )

        versions = self._parse_updates(html)
        if not versions:
            return ScraperResult(
                success=False,
                error=f"No versions found for {device_name} at {pages[link_text]}",
            )

        return ScraperResult(success=True, firmware_versions=versions)
