import logging
import os
import re
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class KorgScraper(BaseScraper):
    """Korg, read from the per-product Downloads pages its support index links to.

    Each page is a set of labelled sections, and the label is what makes this
    tractable -- the same page carries four kinds of thing that all look like
    releases:

        Manuals   minilogue xd/Owner's Manual (English)      2025.07.17
        Software  minilogue xd/Sound Librarian        1.0.5  2019.11.08
        Software  minilogue xd/System Updater         2.10   2020.03.10
        Drivers   minilogue xd/KORG USB-MIDI Driver   1.15 r63e  2026.01.20

    Only the third is the instrument's firmware. Scoping to the Software section
    drops the drivers and the manuals; requiring the updater wording drops the Sound
    Librarian beside it. Both filters are needed: Grandstage X's Manuals section
    contains "Korg System Updater Owner's Manual (English)", which matches the
    wording and is a PDF about the updater rather than the updater.

    Structure, not text. Each entry is a `div.dlFileTitle` holding two `h3` -- name
    then version -- and a `small` carrying "2020.03.10 / ZIP : 1.0MB". Read as flat
    text the file size and the date read as versions, and the manual dates attach to
    whatever follows them.

    Korg writes the updater three ways, and two of them put the version in the name
    rather than in its own heading:

        minilogue xd/System Updater              <h3>2.10</h3>
        kaossilator 2/Operating System Update 1.08
        FISA SUPREMA C/Piano System Updater 1.04

    So the version heading is preferred and the name is the fallback. A pattern
    reading only the heading loses the second and third silently.

    **Only products that actually publish firmware are listed.** The support index
    offers 757 products and about half of the current ones carry an updater -- the
    rest are apps, accessories and instruments that take no firmware. Listing all of
    them would add roughly a hundred devices that can never report a version, which
    is the Focusrite failure repeated deliberately. The device list fetches each
    candidate once, keeps what it finds, and `fetch_firmware_versions` then costs
    nothing.

    Discontinued products are skipped. The index separates them from "on sale" under
    each category heading, and a discontinued instrument will not see another
    release; including them would double the fetch count for nothing.

    **One fifth of the catalogue per run.** This is the only scraper here that does
    not check everything every time, so the reason is worth stating plainly: Korg
    publishes no listing covering more than one product, and there are 164 current
    products in the tracked categories. Measured, a page takes 4.84s, so a full
    sweep is 794s against a 900s hard timeout -- the first live run was killed by it.
    The next most expensive scraper in the repo fetches 61 pages.

    So the candidates are sorted by URL and strided into five batches of 33, and the
    day of the year picks one:

        batch = date.today().toordinal() % 5

    No stored state, self-rotating, and two machines scraping on the same day do the
    same work. Striding a sorted list rather than hashing each URL is what keeps the
    batches even -- hashing gave 41/33/56/34 on this catalogue, and the point of
    batching is a predictable ceiling. A product Korg adds shifts some assignments by
    one position, which costs at most one product being checked a day late.

    Every product is therefore seen every five days rather than daily, and
    `last_seen_at` records when each was actually confirmed, so nothing claims to be
    fresher than it is. Products outside today's batch report `not_checked` rather
    than an empty success: an empty success asserts that Korg publishes nothing for
    them, which would be a lie four days in five, and would bury them in
    `devices_unexplained`.

    Set `KORG_FULL_SWEEP=1`, or construct with `full_sweep=True`, to do all five
    batches in one run. That is the catch-up path -- a first import, or after the
    scraper has been broken -- and it costs the full 794s, so it is deliberate rather
    than the default.
    """

    manufacturer_name = "Korg"
    manufacturer_slug = "korg"
    manufacturer_website = "https://www.korg.com"

    INDEX_URL = "https://www.korg.com/us/support/download/"

    # Index categories worth fetching, and the category each maps to here. Tuners,
    # accessories, digital pianos and computer gear are left out: they are either
    # firmware-less or a different kind of product than this app tracks.
    CATEGORIES = {
        "Synthesizers / Keyboards": "synthesizer",
        "DJ & Production Tools": "other",
        "Drums & Percussion": "synthesizer",
        "Effects": "guitar_pedal",
    }

    ON_SALE = "on sale"
    DISCONTINUED = "Discontinued products"

    SOFTWARE_SECTION = "Software"

    # "System Updater", "Operating System Update 1.08", "Piano System Updater 1.04".
    # Deliberately not just "update": every Manuals entry for an updater matches that,
    # and so does "Update Guide".
    UPDATER = re.compile(r"\bsystem\s+updat(?:er|e)\b", re.I)

    # A version in the entry name, for the products that put it there.
    NAME_VERSION = re.compile(r"(\d+(?:\.\d+)+)\s*$")

    # "2020.03.10 / ZIP : 1.0MB" -- the date is the part before the slash.
    ENTRY_DATE = re.compile(r"(\d{4})\.(\d{2})\.(\d{2})")

    # Five batches of ~33. Raising this shortens each run and lengthens the time for
    # a release to surface; lowering it does the reverse. At 5 the worst run is ~160s
    # and every product is seen within five days.
    BATCHES = 5

    FULL_SWEEP_ENV = "KORG_FULL_SWEEP"

    def __init__(self, *args, full_sweep: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        # product name -> versions, filled by fetch_device_list so the firmware pass
        # costs no further requests.
        self._firmware: Optional[Dict[str, List[ScrapedFirmware]]] = None
        self._urls: Dict[str, str] = {}
        self._categories: Dict[str, str] = {}
        # The registry constructs scrapers with no arguments, so the environment is
        # the only route for an operator; the argument is for tests and scripts.
        self._full_sweep = full_sweep or os.getenv(self.FULL_SWEEP_ENV, "").strip().lower() in (
            "1", "true", "yes", "on",
        )

    def _today_batch(self) -> int:
        return date.today().toordinal() % self.BATCHES

    def _select_batch(self, candidates: List[Tuple[str, str, str]]) -> List[Tuple[str, str, str]]:
        """Today's fifth of the catalogue, or all of it on a full sweep.

        Sorted by URL first so the striding is stable across runs: the index's own
        order is presentation, and a reordering there would otherwise reshuffle every
        batch at once.
        """
        ordered = sorted(candidates, key=lambda candidate: candidate[1])
        if self._full_sweep:
            return ordered
        return ordered[self._today_batch():: self.BATCHES]

    def _index_candidates(self, html: str) -> List[Tuple[str, str, str]]:
        """(name, url, category) for current products in the categories we want.

        The index has no per-category container: it is a flat run of headings and
        links, where an `h3`/`h4` names either a category or "on sale" /
        "Discontinued products". So the document is walked in order and the current
        heading pair is tracked.
        """
        soup = self.parse_html(html)
        found: List[Tuple[str, str, str]] = []
        seen = set()
        category: Optional[str] = None
        state: Optional[str] = None

        for element in soup.find_all(["h3", "h4", "a"]):
            if element.name in ("h3", "h4"):
                text = element.get_text(" ", strip=True)
                if text in (self.ON_SALE, self.DISCONTINUED):
                    state = text
                elif text:
                    category, state = text, None
                continue

            href = element.get("href") or ""
            if "/support/download/product/" not in href:
                continue
            if state != self.ON_SALE or category not in self.CATEGORIES:
                continue

            name = element.get_text(" ", strip=True)
            url = urljoin(self.manufacturer_website, href)
            if not name or url in seen:
                continue
            seen.add(url)
            found.append((name, url, self.CATEGORIES[category]))

        return found

    def _parse_date(self, text: str) -> Optional[datetime]:
        match = self.ENTRY_DATE.search(text or "")
        if not match:
            return None
        try:
            return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None

    def _parse_product(self, html: str) -> List[ScrapedFirmware]:
        """Read the Software section's updater entries."""
        soup = self.parse_html(html)
        best: Dict[str, ScrapedFirmware] = {}

        for section in soup.select("div.com_contents"):
            # The section's own label is an h3 directly under it; entry names are h3
            # too, but nested inside div.dlFileTitle.
            label = section.find("h3", recursive=False)
            if not label or label.get_text(" ", strip=True) != self.SOFTWARE_SECTION:
                continue

            for entry in section.select("div.dlFileTitle"):
                headings = entry.find_all("h3")
                if not headings:
                    continue
                name = headings[0].get_text(" ", strip=True)
                if not self.UPDATER.search(name):
                    continue

                version = None
                if len(headings) > 1:
                    version = headings[1].get_text(" ", strip=True) or None
                if not version:
                    in_name = self.NAME_VERSION.search(name)
                    version = in_name.group(1) if in_name else None
                if not version:
                    continue

                note = entry.find("small")
                release_date = self._parse_date(note.get_text(" ", strip=True) if note else "")

                # Windows and macOS builds of one release sit as separate entries with
                # the same version and date, so one wins rather than both.
                if version not in best:
                    best[version] = ScrapedFirmware(
                        version=version, release_date=release_date
                    )

        return sorted(
            best.values(), key=lambda fw: self._version_key(fw.version), reverse=True
        )

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(part) for part in re.findall(r"\d+", version)) or (0,)

    async def fetch_device_list(self) -> ScraperResult:
        if self._firmware is not None:
            return self._device_result()

        index = await self.fetch_page(self.INDEX_URL)
        if not index:
            return ScraperResult(
                success=False, error=f"Failed to fetch {self.INDEX_URL}"
            )

        candidates = self._index_candidates(index)
        if not candidates:
            return ScraperResult(
                success=False,
                error="Korg's support index listed no current products in the tracked categories",
            )

        batch = self._select_batch(candidates)
        logger.info(
            "Korg: checking %d of %d products (%s)",
            len(batch), len(candidates),
            "full sweep" if self._full_sweep
            else f"batch {self._today_batch() + 1} of {self.BATCHES}",
        )

        firmware: Dict[str, List[ScrapedFirmware]] = {}
        categories: Dict[str, str] = {}

        for name, url, category in batch:
            page = await self.fetch_page(url)
            if not page:
                continue
            versions = self._parse_product(page)
            if not versions:
                # No updater in the Software section. The page loaded, so this is a
                # product that takes no firmware rather than a fetch that broke, and
                # it is left out of the catalogue entirely.
                continue
            firmware[name] = versions
            categories[name] = category
            self._urls[name] = url

        self._firmware = firmware
        self._categories = categories
        return self._device_result()

    def _device_result(self) -> ScraperResult:
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category=self._categories[name],
                    firmware_page_url=self._urls[name],
                    product_url=self._urls[name],
                )
                for name in sorted(self._firmware or {})
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        if self._firmware is None:
            result = await self.fetch_device_list()
            if not result.success:
                return ScraperResult(success=False, error=result.error)

        versions = (self._firmware or {}).get(device_name)
        if versions is None:
            # Either this product is not in today's batch, or Korg has withdrawn it.
            # Both are "we did not look", which is what not_checked says. Claiming an
            # empty success would assert Korg publishes nothing for it -- false four
            # days in five, and it would fill devices_unexplained with the entire
            # catalogue minus a fifth.
            return ScraperResult(success=True, not_checked=True)

        return ScraperResult(success=True, firmware_versions=versions)
