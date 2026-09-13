import re
from datetime import datetime
from typing import Dict, List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class AbletonScraper(BaseScraper):
    """Ableton Live, read from the release notes page for each major version.

    One page per major, and each carries that major's whole history. Live 12's page
    holds 31 releases, Live 11's 36, and both come back from plain aiohttp without a
    browser -- 279KB of rendered text for one request. That makes this among the
    cheapest scrapers here, against Korg's 165 requests for a comparable number of
    products.

    The markup states version and date separately, which is the whole reason this is
    worth scraping rather than guessing:

        <h2>12.4.5
            Release Notes</h2>
        <div class="release_note_text">August 26, 2026 New Features and Improvements ...

    So the version comes from the heading and the date from the opening of the block
    below it. Read as flat text the two run together -- "12.4.5 Release Notes August
    26, 2026 New Features" -- and the same page mentions "Live 12", "Max 8.6" and
    "macOS 13" in prose, which a looser pattern collects as releases.

    **A major version is the product, following Steinberg.** The database already
    holds "Cubase 12" and "Cubase 13" as separate device models because the tiers
    share numbering within a major and not across them, and Live works the same way:
    12.4.5 belongs to Live 12 and says nothing about Live 11. Tracking a single
    "Ableton Live" row would mean 11.3.43 and 12.4.5 competing to be the latest, and
    the newer would always win, which is wrong for anyone who has not paid to upgrade.

    **Live 11 and 12 only.** Pages exist for Live 9 and Live 10 and parse fine, with
    34 and 28 releases. They are left out because neither will ever gain another: the
    catalogue would carry 62 frozen rows whose only function is to report a version
    that cannot change. The same reasoning keeps Korg's discontinued products and
    Eventide's legacy line out. Adding them later is one line each if that judgement
    turns out wrong.

    Push has no release notes page of its own -- `/en/release-notes/push/` is a 404 --
    because Push firmware ships inside Live rather than being versioned separately.
    There is nothing to track for it.
    """

    manufacturer_name = "Ableton"
    manufacturer_slug = "ableton"
    manufacturer_website = "https://www.ableton.com"

    RELEASE_NOTES = "https://www.ableton.com/en/release-notes/{slug}/"

    # Product name -> the slug in its release-notes URL. Current major first.
    PRODUCTS = {
        "Live 12": "live-12",
        "Live 11": "live-11",
    }

    # "12.4.5\n        Release Notes" -- the version leads the heading.
    HEADING_VERSION = re.compile(r"^(\d+(?:\.\d+)+)\b")

    # "August 26, 2026" and "Aug 6, 2024", as the entire text of its own element.
    # Both spellings appear: 12.0.20 uses the short one, and requiring the long form
    # dropped its date while the version parsed fine.
    #
    # The month is captured and looked up by its first three letters rather than
    # handed to strptime, so the pattern cannot accept a spelling the parser then
    # rejects -- the failure that left every Elektron MKII page undated.
    RELEASE_DATE = re.compile(
        r"(January|February|March|April|May|June|July|August|September|"
        r"October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"\.?\s+(\d{1,2}),\s+(\d{4})"
    )

    MONTHS = {month: index for index, month in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun",
         "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

    # How far into a release block to look for that element. The date is the first
    # child on most entries and the second on those opening with a section heading;
    # beyond that it would be a date inside the changelog itself.
    DATE_SEARCH_DEPTH = 6

    NOTES_CLASS = "release_note_text"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._releases: Dict[str, List[ScrapedFirmware]] = {}

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(part) for part in re.findall(r"\d+", version)) or (0,)

    def _release_date(self, body) -> Optional[datetime]:
        """The date element in a release block, or None where there is no date.

        Ableton puts it three ways. Most entries open with an `h4` holding nothing but
        the date; some open with a section heading and put the date in the `p` below
        it; and the older Live 11 point releases carry no date at all -- 11.0.6 and
        11.0.10 through 11.0.12 begin straight into "Bugfixes:".

        Matched against an element's *entire* text rather than searched for, because
        the changelogs themselves mention dates, and an anchored search over the
        flattened block finds only the first shape. That cost 29 of 67 versions
        their date on the first attempt.
        """
        for child in list(body.children)[: self.DATE_SEARCH_DEPTH]:
            if getattr(child, "name", None) is None:
                continue
            text = child.get_text(" ", strip=True)
            matched = self.RELEASE_DATE.fullmatch(text)
            if matched:
                month, day, year = matched.groups()
                try:
                    return datetime(
                        int(year), self.MONTHS[month[:3].lower()], int(day)
                    )
                except (ValueError, KeyError):
                    return None
        return None

    def _parse_releases(self, html: str) -> List[ScrapedFirmware]:
        """Read every release on one major's page, newest first."""
        soup = self.parse_html(html)
        versions: List[ScrapedFirmware] = []
        seen = set()

        for heading in soup.find_all(["h2", "h3"]):
            match = self.HEADING_VERSION.match(heading.get_text(" ", strip=True))
            if not match:
                continue
            version = match.group(1)
            if version in seen:
                continue

            body = heading.find_next_sibling()
            if body is None or self.NOTES_CLASS not in (body.get("class") or []):
                # A heading shaped like a version with no notes under it is a
                # navigation entry, not a release.
                continue
            seen.add(version)

            release_date = self._release_date(body)
            text = body.get_text(" ", strip=True)
            changelog = text
            if release_date is not None:
                # Drop the date from the front of the changelog when it leads.
                leading = self.RELEASE_DATE.match(text)
                if leading:
                    changelog = text[leading.end():].strip()

            # Both spellings of the month are also stripped where the date opened the
            # block, so the changelog reads as changes rather than as a datestamp.

            versions.append(
                ScrapedFirmware(
                    version=version,
                    release_date=release_date,
                    changelog=changelog[:500] or None,
                )
            )

        return sorted(versions, key=lambda fw: self._version_key(fw.version), reverse=True)

    async def _load(self, product: str) -> Optional[List[ScrapedFirmware]]:
        if product in self._releases:
            return self._releases[product]

        slug = self.PRODUCTS.get(product)
        if slug is None:
            return None

        html = await self.fetch_page(self.RELEASE_NOTES.format(slug=slug))
        if not html:
            return None

        releases = self._parse_releases(html)
        if not releases:
            return None
        self._releases[product] = releases
        return releases

    async def fetch_device_list(self) -> ScraperResult:
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category="vst_plugin",
                    firmware_page_url=self.RELEASE_NOTES.format(slug=slug),
                    product_url=self.RELEASE_NOTES.format(slug=slug),
                )
                for name, slug in self.PRODUCTS.items()
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        releases = await self._load(device_name)
        if releases is None:
            return ScraperResult(
                success=False,
                error=f"No release notes read for {device_name} at {firmware_page_url}",
            )
        return ScraperResult(success=True, firmware_versions=releases)
