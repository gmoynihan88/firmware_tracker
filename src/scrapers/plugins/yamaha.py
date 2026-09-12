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

    No dates, checked rather than assumed. The download pages and the updater pages
    behind them carry version history -- the MONTAGE M updater page lists every step
    from "V1.00 to V1.10" up to "V3.00 to V3.01" with its changes -- and not one
    release date among them. The only dates on those pages are a page-level
    "Last updated: July 10, 2024" stamp and copyright years, neither of which belongs
    to a release.

    That version history is worth reading one day: it would turn the single version
    each product reports into roughly ten with changelogs, at one more fetch per
    family. It is not read yet.
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
        ("reface CS", "synthesizer",
         "https://usa.yamaha.com/support/updates/reface_csdx_updater_for_mac.html"),
        ("reface DX", "synthesizer",
         "https://usa.yamaha.com/support/updates/reface_csdx_updater_for_mac.html"),
        ("reface CP", "synthesizer",
         "https://usa.yamaha.com/support/updates/reface_cp_updater_for_mac.html"),
        ("reface YC", "synthesizer",
         "https://usa.yamaha.com/support/updates/reface_yc_updater_for_mac.html"),
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
        """
        title = self.parse_html(html).title
        return bool(title) and self.LANDING_TITLE in title.get_text(strip=True)

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

        updater = self._parse_updater_page(html)
        if updater:
            return ScraperResult(success=True, firmware_versions=updater)

        soup = self.parse_html(html)
        firmware_versions = []
        all_text = soup.get_text()

        # Yamaha versions look like "V1.20" or "Ver.1.20" or "Version 1.20"
        version_pattern = r"[Vv](?:er\.?|ersion)?\s*(\d+\.\d+(?:\.\d+)?)"

        # Yamaha support pages have structured download sections
        sections = soup.find_all(
            ["div", "section", "article", "tr", "li", "td"],
            class_=re.compile(r"download|firmware|update|version|content", re.I)
        )

        # Also look at table rows
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            sections.extend(rows)

        for section in sections:
            text = section.get_text()
            version_match = re.search(version_pattern, text)

            if version_match:
                version = version_match.group(1)

                # Find download link
                download_link = section.find("a", href=re.compile(r"\.(zip|exe|dmg|bin)", re.I))
                download_url = download_link["href"] if download_link else None
                if download_url and not download_url.startswith("http"):
                    download_url = f"https://usa.yamaha.com{download_url}"

                # Yamaha uses various date formats
                date_patterns = [
                    (r"(\w+)\s+(\d{1,2}),?\s+(\d{4})", "%B %d %Y"),  # Month DD, YYYY
                    (r"(\d{4})[/-](\d{2})[/-](\d{2})", "%Y-%m-%d"),  # YYYY-MM-DD
                    (r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", None),    # MM/DD/YYYY or DD/MM/YYYY
                ]
                release_date = None

                for pattern, fmt in date_patterns:
                    date_match = re.search(pattern, text)
                    if date_match:
                        try:
                            if fmt:
                                date_str = " ".join(date_match.groups())
                                release_date = datetime.strptime(date_str.replace(",", ""), fmt)
                            else:
                                # Assume MM/DD/YYYY for US site
                                m, d, y = date_match.groups()
                                release_date = datetime(int(y), int(m), int(d))
                            break
                        except ValueError:
                            continue

                # Get changelog/notes
                changelog = None
                notes_elem = section.find(["ul", "div", "p"], class_=re.compile(r"note|change|detail|description", re.I))
                if notes_elem:
                    changelog = notes_elem.get_text(strip=True)[:500]

                firmware_versions.append(
                    ScrapedFirmware(
                        version=version,
                        release_date=release_date,
                        download_url=download_url,
                        changelog=changelog,
                    )
                )

        # Deduplicate
        seen = set()
        unique = []
        for fw in firmware_versions:
            if fw.version not in seen:
                seen.add(fw.version)
                unique.append(fw)
        firmware_versions = unique

        # Fallback: scan entire page
        if not firmware_versions:
            matches = re.findall(version_pattern, all_text)
            seen = set()
            for version in matches:
                if version not in seen:
                    seen.add(version)
                    firmware_versions.append(ScrapedFirmware(version=version))

        return ScraperResult(success=True, firmware_versions=firmware_versions)
