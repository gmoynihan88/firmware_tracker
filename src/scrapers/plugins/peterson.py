import re
from datetime import datetime
from typing import Dict, List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class PetersonScraper(BaseScraper):
    """Peterson strobe tuners, read from the firmware history on their support page.

    The previous version pointed at product pages on the shop, which carry prices and
    no firmware at all. What it stored as versions were **manual revisions** picked up
    from elsewhere on the site -- "StroboStomp HD English v1.1", "StroboStomp LE
    English v1.1" -- which is why four of six products reported 1.1. That is the
    "User Guide V4" false positive, and it survived because the numbers look exactly
    like firmware.

    The real source is one page. `/support/` has a Firmware History section, one
    `div.firmwareEntry` per release:

        <h3>StroboStomp HD Version 1.0.34</h3>
        <p class="dateTime">Friday, May 2, 2025 11:39:25 AM EDT</p>
        <ul><li>New settings screen parameter for 'Power Up Mute State'</li></ul>

    So one fetch covers the whole range with exact dates and changelogs, and the
    tuners themselves are the products this history names.

    **The visible entry is read, not the JSON beside it.** Each entry also carries its
    release as JSON in a `data-update` attribute, and this scraper used to read that.
    The attribute is single-quoted, so a note containing an apostrophe ends it early:
    StroboStomp HD and LE 1.0.34, the newest release for both, failed to parse and
    were skipped without a word for over a year while 1.0.33 showed as current. On
    the 56 entries whose JSON does parse, the visible heading, date and notes agree
    with it exactly -- and the list shows only the notes the JSON flags public, so
    Peterson's unpublished notes ("not for public consumption") stay out either way.
    Checked 2026-09-15.

    Peterson writes StroboPLUS where the database has StroboPlus HD, so that name is
    mapped back. Getting it wrong creates a second row and orphans the one a user's
    devices are attached to.
    """

    manufacturer_name = "Peterson"
    manufacturer_slug = "peterson"
    manufacturer_website = "https://www.petersontuners.com"

    SUPPORT_URL = "https://www.petersontuners.com/support/"

    # The page's name -> the database's, for rows catalogued under another spelling.
    # StroboPLUS HDC was added under the page's own spelling and needs no entry.
    RENAMES = {"StroboPLUS HD": "StroboPlus HD"}

    HEADING = re.compile(r"^(?P<product>.+?)\s+Version\s+(?P<version>\d+(?:\.\d+)+)$")

    # "Friday, May 2, 2025 11:39:25 AM EDT". The weekday and time are not needed, and
    # the month is looked up by its first three letters rather than handed to strptime.
    DATE = re.compile(r"^[A-Za-z]+,\s+(?P<month>[A-Za-z]+)\.?\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})\b")
    MONTHS = {m: i for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun",
         "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The whole range comes from one page, so it is fetched once per run.
        self._history: Optional[Dict[str, List[ScrapedFirmware]]] = None

    def _release_date(self, text: str) -> Optional[datetime]:
        match = self.DATE.match(text)
        if not match:
            return None
        try:
            return datetime(
                int(match.group("year")),
                self.MONTHS[match.group("month")[:3].lower()],
                int(match.group("day")),
            )
        except (ValueError, KeyError):
            return None

    def _parse_history(self, html: str) -> Dict[str, List[ScrapedFirmware]]:
        """Every release, keyed by product name, in the page's order of products."""
        history: Dict[str, List[ScrapedFirmware]] = {}

        for entry in self.parse_html(html).select("div.firmwareEntry"):
            heading = entry.find("h3")
            match = self.HEADING.match(heading.get_text(" ", strip=True)) if heading else None
            if not match:
                continue

            product = match.group("product")
            product = self.RENAMES.get(product, product)

            stamp = entry.select_one("p.dateTime")
            notes = [li.get_text(" ", strip=True) for li in entry.select("ul li")]

            history.setdefault(product, []).append(
                ScrapedFirmware(
                    version=match.group("version"),
                    release_date=self._release_date(stamp.get_text(" ", strip=True)) if stamp else None,
                    changelog=" ".join(n for n in notes if n)[:500] or None,
                )
            )

        return history

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(p) for p in re.findall(r"\d+", version)) or (0,)

    async def _load(self) -> Optional[Dict[str, List[ScrapedFirmware]]]:
        if self._history is None:
            html = await self.fetch_page(self.SUPPORT_URL)
            if not html:
                return None
            history = self._parse_history(html)
            if not history:
                return None
            self._history = history
        return self._history

    async def fetch_device_list(self) -> ScraperResult:
        history = await self._load()
        if history is None:
            return ScraperResult(
                success=False,
                error=f"No firmware history read from {self.SUPPORT_URL}",
            )

        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    # Pedal tuners are pedals; clip-on and desktop tuners are not.
                    category="guitar_pedal" if "stomp" in name.lower() else "other",
                    firmware_page_url=self.SUPPORT_URL,
                    product_url=self.SUPPORT_URL,
                )
                for name in history
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        history = await self._load()
        if history is None:
            return ScraperResult(
                success=False, error=f"No firmware history read from {self.SUPPORT_URL}"
            )

        versions = history.get(device_name)
        if not versions:
            # StroboRack and Body Beat Sync were catalogued before the list came from
            # this page, and take no firmware; the history does not name them.
            return ScraperResult(success=True, firmware_versions=[])

        return ScraperResult(
            success=True,
            firmware_versions=sorted(
                versions, key=lambda fw: self._version_key(fw.version), reverse=True
            ),
        )
