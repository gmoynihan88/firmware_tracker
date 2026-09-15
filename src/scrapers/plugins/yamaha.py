import re
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class YamahaScraper(BaseScraper):
    """Yamaha, read from the downloads pages of its music-production families.

    **The families come from the music-production index.** /products/music_production/
    links its categories -- synthesizers, stage keyboards, music production studios,
    interfaces, controllers -- and each category page links its product families. A
    family's downloads page is read, and a family is listed when its table carries an
    OS updater; the updater row names the products it serves ("CK61/CK88", "MODX",
    "MONTAGE M"), and a family prefix is expanded to the models its specs page names
    in the table header (MODX8, MODX7, MODX6). Accessories and apps are skipped:
    neither category carries firmware, and together they are thirty pages a day.

    Until 2026-09-15 the products were a hand-kept list of sixteen. Discovery added
    MODX M8/M7/M6, MOXF6/MOXF8, CK61/CK88, CP88/CP73 and YC61/YC73/YC88 -- the last
    four families write their updater "CK61/CK88 V1.10 Operating System Updater",
    version before the word, which the pattern here did not read either. The THR-II
    amps and the G10T transmitter are guitar products outside this index, and stay
    on the one page that states their firmware.

    Eleven of the sixteen products pointed at URLs like
    `/support/updates/montagem6_firm.html`. Those never existed: every one returned
    the same landing page as a slug invented to test it, and the scraper reported
    the products as having no firmware, which claims a verified absence where there
    is a broken URL.

    The real pages were found in `/sitemap.xml`, which lists 20,951 URLs including
    2,334 under /support/updates/. Guessing slugs had failed against eleven shapes,
    the updates index renders only navigation, and the one working page links to no
    siblings -- the sitemap was the thing that was never tried.

    Two shapes, and one page usually covers a family:

        .../synthesizers/montagem/downloads.html   MONTAGE M OS Updater V3.01
        .../synthesizers/modx/downloads.html       MODX OS Updater V2.52
        .../seqtrak/downloads.html                 SEQTRAK OS Updater V2.00
        /support/updates/reface_cp_updater_for_mac.html   reface CP updater V1.30-3

    reface CS and DX share an updater; CP and YC have their own.

    The download pages also list "Yamaha Steinberg USB Driver V2.1.9" and
    "USB-MIDI Driver V1.3.2-2", so the pattern requires the word Updater. They carry
    file sizes too -- 3.91GB, [12.9MB] -- which a looser version pattern reads as
    releases.

    The THR Remote page is unchanged and still works. It lists amp firmware as
    compatibility notes: "[Firmware Ver.1.50 for THR-II]" covers the four THR-II
    amps, and "[Firmware Ver.1.10 for THR30IIA Wireless]" is the G10T transmitter
    that ships with the wireless model, which is why a Line 6 product appears here.

    Dates come from the downloads tables, which have a "Last Update" column:

        Name                                          OS   Size    Last Update
        MONTAGE M OS Updater V3.01 from version V3.00  -   75.4MB  2026-01-14
        Yamaha Steinberg USB Driver V2.1.9 for Win    Win   8.2MB  2025-06-25

    An earlier version of this scraper recorded no dates and said there were none.
    There are, and the reason they were missed is worth keeping: flattened to text
    the date lands *after* its own row's size and immediately before the next row's
    name, so "75.4MB 2026-01-14 Yamaha Steinberg USB Driver" reads as though the
    date introduces the driver. Every date on the page appears to belong to the
    entry below it. Reading the table cells instead of the text removes the
    ambiguity entirely -- structure over free text, for a page where free text is
    not merely unreliable but consistently off by one row.

    The reface products moved to the same kind of page. They had been pointed at
    `/support/updates/reface_*_updater_for_mac.html`, which are download gates
    carrying a EULA and no table. `/products/.../reface/downloads.html` lists all
    four with dates, and one row covers CS and DX together.

    Five products still have no date, and it is an absence rather than a gap:

      - THR30II, THR10II and their Wireless versions. Their firmware appears only
        as compatibility notes on the THR Remote page ("[Firmware Ver.1.50 for
        THR-II]"), which carries no dates. The THR-II downloads page does have a
        dated row -- "THR Remote V1.6.0 ... 2025-12-17" -- but that is the desktop
        editor, not the amp, and its numbering runs on its own track.
      - Line 6 G10TII, for the same reason.

    The only other date anywhere near these pages is "Last updated: July 10, 2024",
    which is identical on the THR Remote page and all three reface updater pages
    because it is the end of the licence agreement, not a release.
    """

    manufacturer_name = "Yamaha"
    manufacturer_slug = "yamaha"
    manufacturer_website = "https://usa.yamaha.com"

    # THR Remote page contains firmware version info for THR amps
    THR_REMOTE_URL = "https://usa.yamaha.com/support/updates/thr_remote_mac.html"

    # Guitar products outside the music-production index, whose firmware is stated only
    # as compatibility notes on the THR Remote app's page.
    THR_PRODUCTS = [
        ("THR30II Wireless", "guitar_pedal"),
        ("THR30II", "guitar_pedal"),
        ("THR10II Wireless", "guitar_pedal"),
        ("THR10II", "guitar_pedal"),
        ("Line 6 G10TII", "wireless_system"),
    ]

    SITE = "https://usa.yamaha.com"
    MUSIC_PRODUCTION_INDEX = "https://usa.yamaha.com/products/music_production/index.html"
    CATEGORY_LINK = re.compile(r"^(?:https://usa\.yamaha\.com)?/products/music_production/(?P<category>[a-z0-9_-]+)/index\.html$")
    FAMILY_LINK = re.compile(
        r"^(?:https://usa\.yamaha\.com)?/products/music_production/(?P<category>[a-z0-9_-]+)/(?P<family>[a-z0-9_+-]+)/index\.html$"
    )
    SKIP_CATEGORIES = {"accessories", "apps"}

    CATEGORIES = {
        "synthesizers": "synthesizer",
        "stagekeyboards": "synthesizer",
        "music-production-studios": "synthesizer",
        "interfaces": "audio_interface",
        "controllers": "midi_controller",
        "midi_controllers": "midi_controller",
    }

    # The specs page's name -> the database's, for rows catalogued in another case.
    RENAMES = {"MONTAGE M8x": "Montage M8x", "MONTAGE M7": "Montage M7", "MONTAGE M6": "Montage M6"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._catalogue: Optional[Dict[str, dict]] = None
        self._pages: Dict[str, str] = {}

    def _links(self, html: str, pattern: re.Pattern) -> List[re.Match]:
        matches, seen = [], set()
        for anchor in self.parse_html(html).find_all("a", href=True):
            match = pattern.match(anchor["href"])
            if match and match.group(0) not in seen:
                seen.add(match.group(0))
                matches.append(match)
        return matches

    def _spec_models(self, html: str) -> List[str]:
        """Model names from a specs page's table headers, in page order."""
        models: List[str] = []
        for cell in self.parse_html(html).find_all("th"):
            text = cell.get_text(" ", strip=True)
            if text and len(text) <= 30 and text not in models:
                models.append(text)
        return models

    def _updater_prefixes(self, html: str) -> List[str]:
        """The product prefixes a downloads table's updater rows name, in order."""
        prefixes: List[str] = []
        for table in self.parse_html(html).find_all("table"):
            rows = table.find_all("tr")
            header = [c.get_text(" ", strip=True) for c in rows[0].find_all(["td", "th"])] if rows else []
            if "Last Update" not in header:
                continue
            for row in rows[1:]:
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue
                name = cells[0].get_text(" ", strip=True)
                if not self._updater_version(name):
                    continue
                for prefix in self._row_prefixes(name):
                    if prefix not in prefixes:
                        prefixes.append(prefix)
        return prefixes

    async def _load(self) -> Optional[Dict[str, dict]]:
        """Every product an OS updater on a family's downloads page serves."""
        if self._catalogue is not None:
            return self._catalogue

        index = await self.fetch_page(self.MUSIC_PRODUCTION_INDEX)
        categories = [m for m in (self._links(index, self.CATEGORY_LINK) if index else [])
                      if m.group("category") not in self.SKIP_CATEGORIES]
        if not categories:
            return None

        catalogue: Dict[str, dict] = {}
        for category in categories:
            page = await self.fetch_page(urljoin(self.SITE, category.group(0)))
            if not page:
                return None
            for family in self._links(page, self.FAMILY_LINK):
                base = urljoin(self.SITE, family.group(0)).rsplit("/", 1)[0]
                downloads_url = f"{base}/downloads.html"
                downloads = await self.fetch_page(downloads_url)
                if not downloads:
                    # A family whose page does not load would drop its products silently.
                    return None
                self._pages[downloads_url] = downloads
                prefixes = self._updater_prefixes(downloads)
                if not prefixes:
                    continue

                specs = await self.fetch_page(f"{base}/specs.html") or ""
                models = self._spec_models(specs)
                for prefix in prefixes:
                    named = [m for m in models if m.lower().startswith(prefix.lower())] or [prefix]
                    for model in named:
                        catalogue.setdefault(self.RENAMES.get(model, model), {
                            "url": downloads_url,
                            "category": self.CATEGORIES.get(category.group("category"), "other"),
                        })

        if not catalogue:
            return None
        self._catalogue = catalogue
        return catalogue

    async def fetch_device_list(self) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(
                success=False,
                error=f"Could not read Yamaha's music-production families from {self.MUSIC_PRODUCTION_INDEX}",
            )

        devices = [
            ScrapedDevice(
                name=name,
                category=entry["category"],
                firmware_page_url=entry["url"],
                product_url=entry["url"].replace("/downloads.html", "/index.html"),
            )
            for name, entry in catalogue.items()
        ]
        devices += [
            ScrapedDevice(
                name=name,
                category=category,
                firmware_page_url=self.THR_REMOTE_URL,
                product_url=self.THR_REMOTE_URL,
            )
            for name, category in self.THR_PRODUCTS
        ]
        return ScraperResult(success=True, devices=devices)

    # Every dead product URL serves this, and so does a slug made up to test it. A
    # live page titles itself after the download -- "THR Remote V1.6.0 for Mac".
    LANDING_TITLE = "Firmware / Software Updates"

    # "MONTAGE M OS Updater V3.01", "reface CP updater V1.30-3 for Mac". Requiring
    # "Updater" is what keeps out the drivers listed on the same pages -- "Yamaha
    # Steinberg USB Driver V2.1.9", "USB-MIDI Driver V1.3.2-2" -- and the file sizes
    # beside them, 3.91GB and [12.9MB], which a looser pattern reads as versions.
    UPDATER = re.compile(
        r"(?:OS\s+)?[Uu]pdater\s+V\s*(\d+(?:\.\d+)+(?:-\d+)?)", re.I
    )

    # The stage keyboards and MOXF put the version first: "CK61/CK88 V1.10 Operating
    # System Updater". The pattern above never read those four families.
    OS_UPDATER = re.compile(
        r"^(?P<models>.+?)\s+V\s*(?P<version>\d+(?:\.\d+)+(?:-\d+)?)\s+Operating\s+System\s+Updater\b", re.I
    )

    def _updater_version(self, row_name: str) -> Optional[str]:
        match = self.OS_UPDATER.match(row_name)
        if match:
            return match.group("version")
        match = self.UPDATER.search(row_name)
        return match.group(1) if match else None

    def _row_prefixes(self, row_name: str) -> List[str]:
        """Product prefixes an updater row names, as the page writes them.

        "MODX OS Updater" is MODX; "reface CS/DX updater" is reface CS and reface DX,
        the alternation on the last word; "CK61/CK88 V1.10 Operating System Updater"
        is CK61 and CK88.
        """
        match = self.OS_UPDATER.match(row_name)
        if match:
            prefix = match.group("models").strip()
        else:
            prefix = re.split(r"\s*updater\b", row_name, maxsplit=1, flags=re.I)[0]
            prefix = re.sub(r"\bOS\s*$", "", prefix.strip()).strip()
        if not prefix:
            return []

        head, _, tail = prefix.rpartition(" ")
        if "/" in tail:
            parts = [part for part in tail.split("/") if part]
            return [f"{head} {part}" if head else part for part in parts]
        return [prefix]

    def _is_dead_page(self, html: str) -> bool:
        """Whether Yamaha served its generic landing page instead of a product page.

        Checked on the title rather than the body length, which would break the first
        time Yamaha changed a footer.

        Only the "Firmware / Software Updates" landing page is detectable this way. A
        made-up slug under /products/ returns the *category* index instead -- 200, and
        titled "Synthesizers - Synthesizers & Music Production" -- which no title rule
        separates from a real product page: "reface - Downloads - Synthesizers" has
        Downloads in it and "MONTAGE M Synthesizer Manuals & Software" does not, so
        requiring the word rejects two live pages. What protects against that page is
        that it carries no updater row, and nothing here guesses a version from free
        text any more.
        """
        title = self.parse_html(html).title
        return bool(title) and self.LANDING_TITLE in title.get_text(strip=True)

    def _row_applies_to(self, row_name: str) -> list:
        """Lowercased product prefixes a downloads row covers."""
        return [prefix.lower() for prefix in self._row_prefixes(row_name)]

    def _parse_downloads_table(self, html: str, device_name: str) -> list:
        """Read updater rows and their Last Update dates for one product.

        Only rows whose own name names this product are taken. The same table lists
        "Yamaha Steinberg USB Driver V2.1.9" and "USB-MIDI Driver V3.1.5", each with
        a date of its own, and on the THR-II page "THR Remote V1.6.0" -- the editor
        rather than the amp. Requiring the word Updater excludes all of them.
        """
        wanted = device_name.lower()
        versions = []
        seen = set()

        for table in self.parse_html(html).find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue
            header = [cell.get_text(" ", strip=True) for cell in rows[0].find_all(["td", "th"])]
            if "Last Update" not in header:
                continue
            date_column = header.index("Last Update")

            for row in rows[1:]:
                cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
                if len(cells) <= date_column:
                    continue

                version = self._updater_version(cells[0])
                if not version:
                    continue
                if not any(wanted.startswith(p) for p in self._row_applies_to(cells[0])):
                    continue

                if version in seen:
                    # MONTAGE M lists V3.01 twice, as a full installer and as a step
                    # up from V3.00. One release, two files.
                    continue
                seen.add(version)

                try:
                    release_date = datetime.strptime(cells[date_column], "%Y-%m-%d")
                except ValueError:
                    release_date = None

                versions.append(
                    ScrapedFirmware(version=version, release_date=release_date)
                )

        # Newest first. The table is ordered by platform, not by version -- reface
        # lists V1.30-3, then V1.30, then V1.20 -- and "1.30-3" has to sort above
        # "1.30", so the numbers are compared as tuples rather than as text.
        return sorted(versions, key=lambda fw: self._version_key(fw.version), reverse=True)

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(part) for part in re.findall(r"\d+", version)) or (0,)

    def _parse_updater_page(self, html: str) -> list:
        """Read the OS updater version from a downloads or updater page.

        One page usually serves a whole family -- MONTAGE M6, M7 and M8x share an
        updater, as do reface CS and DX -- so every product reading it gets the same
        version, which is correct rather than the duplication bug it resembles.
        """
        text = re.sub(r"\s+", " ", self.parse_html(html).get_text(" "))
        seen = []
        for match in self.UPDATER.finditer(text):
            version = match.group(1)
            if version not in seen:
                seen.append(version)
        return [ScrapedFirmware(version=v) for v in seen]

    def _parse_thr_remote_page(self, html: str, device_name: str) -> list[ScrapedFirmware]:
        """Parse THR firmware versions from the THR Remote page."""
        soup = self.parse_html(html)
        text = soup.get_text()
        firmware_versions = []

        # THR Remote page contains firmware for both THR-II amps and Line 6 G10TII transmitter
        # Format: "[Firmware Ver.1.50 for THR-II]" or "[Firmware Ver.1.10 for THR30IIA Wireless]"
        # The G10TII transmitter firmware is listed under "THR30IIA Wireless"
        if "G10TII" in device_name:
            # Line 6 G10TII wireless transmitter firmware
            firmware_entries = re.findall(
                r"\[Firmware\s+Ver\.?\s*(\d+\.\d+)\s+for\s+THR30IIA\s+Wireless\]",
                text,
                re.I
            )
        else:
            # THR-II amp firmware applies to all THR-II models
            firmware_entries = re.findall(
                r"\[Firmware\s+Ver\.?\s*(\d+\.\d+)\s+for\s+THR-II\]",
                text,
                re.I
            )

        for version in firmware_entries:
            firmware_versions.append(ScrapedFirmware(version=version))

        return firmware_versions

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        """Fetch firmware versions from Yamaha support pages."""
        # Use Playwright for THR Remote page (JS-rendered)
        if "thr_remote" in firmware_page_url:
            html = await self.fetch_page_js(firmware_page_url, wait_for_timeout=15000)
        elif firmware_page_url in self._pages:
            # Read while listing; the same page serves every model of its family.
            html = self._pages[firmware_page_url]
        else:
            html = await self.fetch_page(firmware_page_url)
            if html:
                self._pages[firmware_page_url] = html

        if not html:
            return ScraperResult(
                success=False, error=f"Failed to fetch {firmware_page_url}"
            )

        if self._is_dead_page(html):
            return ScraperResult(
                success=False,
                error=(
                    f"{firmware_page_url} is gone -- it serves Yamaha's generic "
                    f"updates landing page, the same one an invented slug returns"
                ),
            )

        # Special handling for THR Remote page
        if "thr_remote" in firmware_page_url:
            firmware_versions = self._parse_thr_remote_page(html, device_name)
            if firmware_versions:
                return ScraperResult(success=True, firmware_versions=firmware_versions)

        # The table first: it is the only source that carries dates.
        dated = self._parse_downloads_table(html, device_name)
        if dated:
            return ScraperResult(success=True, firmware_versions=dated)

        updater = self._parse_updater_page(html)
        if updater:
            return ScraperResult(success=True, firmware_versions=updater)

        # No free-text fallback. What stood here scanned the whole page for
        # anything shaped like "V1.20" and, failing that, scanned it again with the
        # same pattern -- on pages that also carry driver versions, file sizes and
        # macOS requirements. Every product now reads either the THR Remote page or
        # a downloads table, so the fallback was unreachable for all sixteen while
        # remaining the thing that would fire if a table ever moved: silently, with
        # a number taken from whatever else was on the page.
        #
        # Reporting nothing is the honest answer. It renders as "Firmware Unknown",
        # which prompts a look; a version scraped off a file size does not.
        return ScraperResult(success=True, firmware_versions=[])
