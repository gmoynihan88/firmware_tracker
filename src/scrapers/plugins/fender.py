import json
import re
from datetime import datetime
from typing import Dict, List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class FenderScraper(BaseScraper):
    """Fender Tone Master amplifiers, read from the Zendesk behind fender.com.

    The site itself is unreachable. Plain aiohttp gets nothing at all -- not the
    support pages, not the homepage -- and a browser gets Cloudflare's "Just a
    moment..." challenge, which a slug invented to test it returns identically, so
    the block is blanket rather than a 404. The challenge does clear after about five
    seconds of waiting, which is long enough that a probe would reasonably give up
    first.

    None of that matters, because the data is not on the site. Support is a Zendesk
    Help Center and `support.fender.com/api/v2/help_center/articles.json` answers
    with no challenge at all. Same move that found UAFX behind UA Connect and
    Novation behind Components: the vendor's own support platform answers where its
    marketing site does not.

    Each amplifier's article states its current firmware in prose, and the Tone
    Master Pro's carries a full history:

        Version Information 12/3/2025
        Tone Master Pro Firmware – v1.7.53 download link

    The date precedes the version, so they are paired by walking the article and
    holding the date of the current "Version Information" block. Fender writes that
    block two ways, and its newest releases use the second:

        Version Information 12/3/2025          date on the same line
        Version Information                    date on the next line, numeric or
        15 Jul 2026                            day-month-year

    Until 2026-09-13 only the first was read, which left the two newest Tone Master
    Pro releases and the Super's 2.0.30 undated -- and this docstring claimed they
    had no date to read.

    **A block's date covers every model released in it.** Twin and Twin Blonde ship
    one firmware, listed one after the other under a single date, and the Deluxe pair
    the same way; taking the date for the first line only left both Blonde models
    undated. A model that appears a second time in one block is another release and
    does not take the date, and a download line with no block above it stays
    undated rather than borrowing the next date down.

    **Three things in these articles look like the amplifier's firmware.** All appear
    within a few lines of the real version:

        Mac – v1.8.4.9728                       the Pro Control app
        PC – v1.8.4.9733                        the same app, other platform
        v5.72.0 (updated 3/26/2025)             the Fender Universal ASIO driver
        macOS Monterey 12.7 or later            an OS requirement

    The ASIO driver is the nastiest: its "updated 3/26/2025" repeats inside every
    release block in the article, so a date search finds it thirteen times and would
    stamp most of the history with one driver's date. The version pattern therefore
    requires the product's own name in front of the word Firmware, and refuses lines
    beginning Mac or PC.

    Mustang, Rumble and Acoustic amps have articles explaining how to update but
    never state a version, so they are absent rather than listed as permanently
    unknown.

    Categorised as guitar pedals, following the Yamaha THR amplifiers already in the
    catalogue -- the category enum has no amplifier, and inventing one for eight rows
    would be worse than the inaccuracy.
    """

    manufacturer_name = "Fender"
    manufacturer_slug = "fender"
    manufacturer_website = "https://www.fender.com"

    ARTICLES_API = (
        "https://support.fender.com/api/v2/help_center/articles.json?per_page=100&page={page}"
    )
    MAX_PAGES = 4

    SUPPORT_URL = "https://support.fender.com/hc/en-us/sections/42423600131099-FIRMWARE-SOFTWARE"

    # "Tone Master Pro Firmware – v1.8.58 download link". The leading guard is what
    # keeps "Mac – v1.8.4.9728" and "PC – v1.8.4.9733" out: those are the Pro Control
    # app, whose numbering runs on its own track.
    FIRMWARE_LINE = re.compile(
        r"^(?!Mac\b|PC\b)(.{3,60}?)\s+Firmware\s*[–—-]\s*v?(\d+(?:\.\d+)+)",
        re.I,
    )

    # "Version Information 12/3/2025", which introduces a release block.
    VERSION_INFO = re.compile(r"^Version\s+Information\s+(\d{1,2})/(\d{1,2})/(\d{4})\s*$", re.I)
    # "Version Information" alone, with its date on the next line.
    VERSION_INFO_ALONE = re.compile(r"^Version\s+Information\s*$", re.I)
    # The next line's date: "6/25/2025" or "15 Jul 2026".
    DATE_NUMERIC = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
    DATE_WORDS = re.compile(r"^(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})$")
    MONTH_NUMBERS = {m: i for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun",
         "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

    # Only lines offering a download are releases; the article repeats the current
    # version in its opening summary without one.
    DOWNLOAD_MARKER = "download link"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._firmware: Optional[Dict[str, List[ScrapedFirmware]]] = None

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(part) for part in re.findall(r"\d+", version)) or (0,)

    @staticmethod
    def _lines(body: str) -> List[str]:
        text = re.sub(r"<[^>]+>", "\n", body or "")
        return [line.strip() for line in text.splitlines() if line.strip()]

    @classmethod
    def _standalone_date(cls, line: str) -> Optional[datetime]:
        """The date on the line after a bare "Version Information", if it is one."""
        text = line.strip()
        try:
            numeric = cls.DATE_NUMERIC.match(text)
            if numeric:
                month, day, year = numeric.groups()
                return datetime(int(year), int(month), int(day))
            words = cls.DATE_WORDS.match(text)
            if words:
                day, month_name, year = words.groups()
                month = cls.MONTH_NUMBERS.get(month_name[:3].lower())
                return datetime(int(year), month, int(day)) if month else None
        except ValueError:
            return None
        return None

    def _parse_article(self, body: str) -> Dict[str, List[tuple]]:
        """(version, date) per product named in one article."""
        found: Dict[str, List[tuple]] = {}
        pending: Optional[datetime] = None
        # Models that have taken this block's date. Siblings released together share
        # it; the same model appearing again in the block is another release.
        dated_in_block: set = set()
        awaiting_date = False

        for line in self._lines(body):
            if awaiting_date:
                awaiting_date = False
                parsed = self._standalone_date(line)
                if parsed is not None:
                    pending = parsed
                    continue
                # Not a date: the block is undated, and this line is read normally.

            if self.VERSION_INFO_ALONE.match(line):
                pending, dated_in_block, awaiting_date = None, set(), True
                continue

            dated = self.VERSION_INFO.match(line)
            if dated:
                month, day, year = dated.groups()
                try:
                    pending = datetime(int(year), int(month), int(day))
                except ValueError:
                    pending = None
                dated_in_block = set()
                continue

            matched = self.FIRMWARE_LINE.match(line)
            if not matched or self.DOWNLOAD_MARKER not in line.lower():
                continue

            name = " ".join(matched.group(1).split())
            if name in dated_in_block:
                date = None
            else:
                date = pending
                if pending is not None:
                    dated_in_block.add(name)
            found.setdefault(name, []).append((matched.group(2), date))

        return found

    async def _load(self) -> Optional[Dict[str, List[ScrapedFirmware]]]:
        if self._firmware is not None:
            return self._firmware

        collected: Dict[str, Dict[str, Optional[datetime]]] = {}
        pages_read = 0

        for page in range(1, self.MAX_PAGES + 1):
            raw = await self.fetch_page(self.ARTICLES_API.format(page=page))
            if not raw:
                break
            try:
                payload = json.loads(raw)
            except ValueError:
                break
            articles = payload.get("articles") or []
            if not articles:
                break
            pages_read += 1

            for article in articles:
                for name, entries in self._parse_article(article.get("body") or "").items():
                    versions = collected.setdefault(name, {})
                    for version, released in entries:
                        # First sighting wins: the newest article states the current
                        # release, and older ones repeat it without a date.
                        if version not in versions or (versions[version] is None and released):
                            versions[version] = released

            if not payload.get("next_page"):
                break

        if not pages_read or not collected:
            return None

        self._firmware = {
            name: sorted(
                (ScrapedFirmware(version=v, release_date=d) for v, d in versions.items()),
                key=lambda fw: self._version_key(fw.version),
                reverse=True,
            )
            for name, versions in collected.items()
        }
        return self._firmware

    async def fetch_device_list(self) -> ScraperResult:
        firmware = await self._load()
        if firmware is None:
            return ScraperResult(
                success=False, error="Could not read Fender's Zendesk articles"
            )

        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category="guitar_pedal",
                    firmware_page_url=self.SUPPORT_URL,
                    product_url=self.SUPPORT_URL,
                )
                for name in sorted(firmware)
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        firmware = await self._load()
        if firmware is None:
            return ScraperResult(
                success=False, error="Could not read Fender's Zendesk articles"
            )

        versions = firmware.get(device_name)
        if versions is None:
            # Fender has retired the article. The API answered, so this is an absence.
            return ScraperResult(success=True, firmware_versions=[])

        return ScraperResult(success=True, firmware_versions=versions)
