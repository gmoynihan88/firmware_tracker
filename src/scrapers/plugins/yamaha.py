import re
from datetime import datetime

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class YamahaScraper(BaseScraper):
    """Yamaha, read from the pages its own sitemap lists.

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

    # Known Yamaha products with firmware updates
    KNOWN_PRODUCTS = [
        ("THR30II Wireless", "guitar_pedal", "https://usa.yamaha.com/support/updates/thr_remote_mac.html"),
        ("THR30II", "guitar_pedal", "https://usa.yamaha.com/support/updates/thr_remote_mac.html"),
        ("THR10II Wireless", "guitar_pedal", "https://usa.yamaha.com/support/updates/thr_remote_mac.html"),
        ("THR10II", "guitar_pedal", "https://usa.yamaha.com/support/updates/thr_remote_mac.html"),
        ("Line 6 G10TII", "wireless_system", "https://usa.yamaha.com/support/updates/thr_remote_mac.html"),
        ("MODX8", "synthesizer", "https://usa.yamaha.com/products/music_production/synthesizers/modx/downloads.html"),
        ("MODX7", "synthesizer", "https://usa.yamaha.com/products/music_production/synthesizers/modx/downloads.html"),
        ("MODX6", "synthesizer", "https://usa.yamaha.com/products/music_production/synthesizers/modx/downloads.html"),
        ("Montage M8x", "synthesizer", "https://usa.yamaha.com/products/music_production/synthesizers/montagem/downloads.html"),
        ("Montage M7", "synthesizer", "https://usa.yamaha.com/products/music_production/synthesizers/montagem/downloads.html"),
        ("Montage M6", "synthesizer", "https://usa.yamaha.com/products/music_production/synthesizers/montagem/downloads.html"),
        ("SEQTRAK", "synthesizer",
         "https://usa.yamaha.com/products/music_production/music-production-studios/seqtrak/downloads.html"),
        ("reface CS", "synthesizer", "https://usa.yamaha.com/products/music_production/synthesizers/reface/downloads.html"),
        ("reface DX", "synthesizer", "https://usa.yamaha.com/products/music_production/synthesizers/reface/downloads.html"),
        ("reface CP", "synthesizer", "https://usa.yamaha.com/products/music_production/synthesizers/reface/downloads.html"),
        ("reface YC", "synthesizer", "https://usa.yamaha.com/products/music_production/synthesizers/reface/downloads.html"),
    ]

    async def fetch_device_list(self) -> ScraperResult:
        """Return the list of known Yamaha products."""
        devices = [
            ScrapedDevice(
                name=name,
                category=category,
                firmware_page_url=url,
                product_url=url.replace("/support/updates/", "/products/").replace("_firm.html", "/"),
            )
            for name, category, url in self.KNOWN_PRODUCTS
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

    @staticmethod
    def _row_applies_to(row_name: str) -> list:
        """Product prefixes a downloads row covers.

        The name runs "<product> [OS] Updater V<version> ...", and one row can cover
        two products: "reface CS/DX updater" is CS and DX, the way one updater file
        serves both instruments.
        """
        prefix = re.split(r"\s*updater\b", row_name, maxsplit=1, flags=re.I)[0]
        prefix = re.sub(r"\bOS\s*$", "", prefix.strip()).strip()
        if not prefix:
            return []

        # "reface CS/DX" -> "reface CS", "reface DX". The alternation is always on
        # the last word, so everything before it is the shared part of the name.
        head, _, tail = prefix.rpartition(" ")
        if head and "/" in tail:
            return [f"{head} {part}".lower() for part in tail.split("/") if part]
        return [prefix.lower()]

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

                match = self.UPDATER.search(cells[0])
                if not match:
                    continue
                if not any(wanted.startswith(p) for p in self._row_applies_to(cells[0])):
                    continue

                version = match.group(1)
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
        else:
            html = await self.fetch_page(firmware_page_url)

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
