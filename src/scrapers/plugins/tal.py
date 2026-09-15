import re
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class TALScraper(BaseScraper):
    """Scraper for TAL Software (Togu Audio Line) virtual instruments and effects.

    The products are the cards on /products, each a `div.productbox` whose `h6` is
    the plug-in's name. Three cards are bundles ("Analog Bundle", "FX Bundle") that
    link to a member's page and are skipped, and the U-NO-LX appears twice, once on
    its own card and once through its bundle.

    Each card's page is rendered once, while listing, and only plug-ins whose page
    states a version are listed. TAL still offers four legacy freebies -- TAL-BassLine,
    TAL-Dub's, TAL-Effects, TAL-U-NO-62 -- whose pages carry no version at all, and a
    row for each would report nothing forever. The rendered pages are kept, so
    fetching versions afterwards costs nothing.

    "No version" alone does not identify those four: a current product page that
    renders without its content states no version either, and TAL-Drum vanished from
    a live listing that way. The freebies are recognised by what they do show -- a
    "Downloads" list and no `#changelog` section -- and any other page without a
    version fails the listing.

    Until 2026-09-15 the products were a hand-kept list of nine; the page listed
    eighteen with versions, among them TAL-J-8X, TAL-Pha, TAL-EQ, TAL-G-Verb,
    TAL-Dub-X and five free effects.

    **A page that fails to render fails the listing**, rather than quietly dropping
    that plug-in for the day. TAL's pages have been slow enough to time out for a
    few minutes at a time; the price of a loud failure then is one missed day.
    """

    manufacturer_name = "TAL Software"
    manufacturer_slug = "tal"
    manufacturer_website = "https://tal-software.com"

    # Known firmware versions (for JS-loaded changelogs)
    KNOWN_FIRMWARE = {
        "TAL-U-NO-LX-V2": [
            ("5.1.3", "2026-03-10", "Minor fixes. Framework update."),
            ("5.1.2", "2025-11-03", "MPE pitch not stay in note release fixed."),
            ("5.1.1", "2025-09-17", "More MPE options to improve compatibility for different MPE hardware devices (Osmose). Framework update. Small UI changes."),
            ("5.0.0", "2025-04-17", "Direct LFO DCO modulation wheel support. Framework update. Small UI changes."),
            ("4.9.5", "2024-11-05", "More flexible serial key verification (header and footer not required)."),
            ("4.9.4", "2024-10-31", "UI changes. Arp in N mode uses round robin fixed. Framework update."),
            ("4.9.3", "2024-06-26", "MIDI CC rendering problem in some DAWs fixed. MIDI LEARN problem fixed."),
            ("4.9.1", "2024-06-21", "Fixes preset arrow CC assignment problems introduced with 4.8.9."),
            ("4.9.0", "2024-05-28", "Fixes preset-arrows not working, introduced with 4.8.9."),
            ("4.8.9", "2024-05-28", "Arp playing without note input when switching presets while playing fixed."),
            ("4.8.8", "2024-05-06", "Arp RR also in normal mode. Fixes arp bug introduced with 4.8.6."),
            ("4.8.6", "2024-05-06", "Minor fixes."),
            ("4.8.5", "2024-05-06", "Arp not play first note under special conditions fixed."),
            ("4.8.4", "2024-02-13", "New MPE keyboard view. Possible crash on some systems fixed."),
            ("4.8.3", "2023-09-18", "Mod and pitch-wheel decoupled from automation. Reduced aliasing. Improved UI resize behaviour."),
            ("4.8.1", "2023-08-16", "Bug fixes."),
            ("4.7.7", "2023-06-14", "New improved preset browser. Poly aftertouch support. Note based velocity support in arpeggiator."),
            ("4.7.4", "2023-02-06", "LED does not show right value fixed."),
            ("4.7.3", "2023-01-12", "AAX native M1 support. Base framework updated (JUCE 7). Minor fixes."),
            ("4.7.2", "2022-08-13", "Compatibility fixes."),
            ("4.6.8", "2022-07-25", "Random unison phases for the very first note. VST2 does not play very first note fixed."),
            ("4.6.6", "2022-07-13", "CLAP MPE now works in Bitwig."),
            ("4.6.4", "2022-07-09", "Voice 1 noise not working fixed."),
            ("4.6.3", "2022-07-05", "Possible crash on windows when pressing a keyboard key fixed. VCO noise oscillator in unison mode improved."),
            ("4.6.2", "2022-07-05", "Round Robin also with arpeggiator."),
            ("4.6.0", "2022-07-02", "CLAP plugin format added. New unisono mode. New round robin voice mode."),
            ("4.5.4", "2021-09-08", "Preset browser fixes. MTS library updated."),
            ("4.5.3", "2021-07-27", "Improved preset browser / fixes."),
            ("4.5.2", "2021-07-15", "MTS (microtuning) lock fixed. Improved preset browser."),
            ("4.5.1", "2021-06-14", "MTS (microtuning) support added."),
            ("4.5.0", "2021-06-07", "New serial protection."),
        ],
        "TAL-J-8": [
            ("2.0.6", "2026-05-26", "Sync LFO fix. Framework update."),
            ("2.0.4", "2025-12-29", "14-bit MPE zone pitch range in Bitwig fixed."),
            ("2.0.3", "2025-12-16", "Problem with host synced square LFO fixed. Framework update."),
            ("2.0.1", "2025-09-17", "More MPE options to improve compatibility for different MPE hardware devices (osmose). Framework update."),
            ("2.0.0", "2025-04-18", "More user interface contrast. Framework updated. Windows UI performance increased."),
            ("1.9.8", "2025-02-05", "UI changes. Preset browser updated."),
            ("1.9.7", "2025-01-02", "Minor fixes. Internal refactorings. Apple notarisation problem fixed."),
            ("1.9.6", "2024-12-19", "Voice tuning dialog display error fixed when switching presets. UI performance drop when voice tuning dialog is open, fixed."),
            ("1.9.3", "2024-12-04", "Registration not working on some systems fixed. Framework update."),
            ("1.9.2", "2024-12-02", "Voice tuning vco settings fixed. Framework update."),
            ("1.9.1", "2024-11-05", "More flexible serial key verification. Voice Control dialog UI fixes. MPE switch not working fixed."),
            ("1.9.0", "2024-10-31", "UI update. Bug fixes. Framework update."),
            ("1.8.4", "2024-06-05", "Microtuning and output settings are not retained fixed."),
            ("1.8.3", "2024-05-23", "1/32 sync mode for LFO added."),
            ("1.8.2", "2024-05-02", "Improved MIDI handling. Bug fixes."),
            ("1.8.1", "2024-03-25", "Stuck in solo mode fixed. More undo/redo steps."),
            ("1.8.0", "2024-03-21", "Minor improvements. CPU optimisations."),
            ("1.7.8", "2023-11-10", "Enable/Disable layer stereo outputs with the MULTI OUT button. Stuck in SOLO mode fixed."),
            ("1.7.6", "2023-08-16", "Bug fixes."),
            ("1.7.1", "2023-06-14", "New improved preset browser. Poly aftertouch support. Note based velocity support in arpeggiator."),
            ("1.6.6", "2023-01-12", "AAX native M1 support. Base framework updated (JUCE 7). Minor fixes."),
            ("1.6.3", "2022-08-10", "Fixes stuck note problem and fixes the wrong voice behaviour introduced with 1.6.2"),
            ("1.6.1", "2022-08-09", "Important MPE timbre fix. CLAP plug-in format added. Jupiter 8 hardware voice mode added. UI updated."),
            ("1.5.5", "2022-04-25", "Round Robin voice mode added."),
            ("1.5.4", "2021-09-20", "Preset browser fixes. X-Mod calibration knob added."),
        ],
    }

    PRODUCTS_URL = "https://tal-software.com/products"

    # The card's name -> the database's.
    RENAMES = {
        "TAL-U-NO-LX": "TAL-U-NO-LX-V2",
        "TAL-Mod": "TAL-MOD",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._catalogue: Optional[Dict[str, dict]] = None

    def _parse_index(self, html: str) -> Dict[str, str]:
        """Plug-in name -> product page, from the index's product cards."""
        products: Dict[str, str] = {}
        for card in self.parse_html(html).select("div.productbox"):
            title = card.find("h6")
            link = card.find("a", href=re.compile(r"/products/[a-z0-9-]+$"))
            if not title or not link:
                continue
            name = title.get_text(" ", strip=True)
            # A bundle's card links to one member's page, which has its own card.
            if name.lower().endswith("bundle"):
                continue
            products[self.RENAMES.get(name, name)] = urljoin(self.PRODUCTS_URL, link["href"])
        return products

    async def _load(self) -> Optional[Dict[str, dict]]:
        """Every plug-in whose page states a version, rendered once per scrape."""
        if self._catalogue is not None:
            return self._catalogue

        # TAL blocks plain HTTP fetches, so the rendered page is the only route in.
        index = await self.fetch_page_js(self.PRODUCTS_URL, wait_for_timeout=20000)
        products = self._parse_index(index) if index else {}
        if not products:
            return None

        catalogue: Dict[str, dict] = {}
        for name, url in products.items():
            html = await self.fetch_page_js(url, wait_for_timeout=20000)
            if not html:
                return None
            versions = self._parse_changelog(html)
            if versions:
                catalogue[name] = {"url": url, "versions": versions}
            elif not self._is_versionless_legacy_page(html):
                # A current product page that rendered without its content. TAL-Drum
                # came back this way once on 2026-09-15 and, before this check, was
                # dropped from the listing as though it had no version.
                return None

        self._catalogue = catalogue
        return catalogue

    def _is_versionless_legacy_page(self, html: str) -> bool:
        """Whether a page that states no version is one of TAL's old freebies.

        Those pages render a "Downloads" list of archives and have no change log. A
        current product page has a `#changelog` section, so one that yields no
        version did not finish rendering -- and neither did a page with no "Downloads"
        at all, which is the app shell.
        """
        soup = self.parse_html(html)
        if soup.find(id="changelog"):
            return False
        return any(line.strip() == "Downloads" for line in soup.get_text("\n").splitlines())

    async def fetch_device_list(self) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(
                success=False,
                error=f"Could not read TAL's products from {self.PRODUCTS_URL}",
            )
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category="vst_plugin",
                    firmware_page_url=entry["url"],
                    product_url=entry["url"],
                )
                for name, entry in catalogue.items()
            ],
        )

    # TAL lists the shipping version on its own in the download block ("v5.1.3")
    # and the history as dated entries ("Version 5.1.2 / 03.11.2025") followed by
    # the change description. Pairing version and date within a single entry is
    # what keeps a release from inheriting its neighbour's date.
    # Spacing after the "v" varies by product page: "v5.1.3" but "v 1.9.8".
    DOWNLOAD_VERSION = re.compile(r"^v\s*(\d+(?:\.\d+)+)$")
    CHANGELOG_ENTRY = re.compile(
        r"^Version\s+(\d+(?:\.\d+)+)\s*/\s*(\d{1,2})\.(\d{1,2})\.(\d{4})$"
    )

    def _parse_changelog(self, html: str) -> List[ScrapedFirmware]:
        """Parse the version history out of a TAL product page."""
        lines = [
            line.strip()
            for line in self.parse_html(html).get_text("\n").splitlines()
            if line.strip()
        ]

        versions: List[ScrapedFirmware] = []
        seen = set()

        # The shipping version is not always in the changelog: 5.1.3 ships while the
        # history starts at 5.1.2. Take it first so it is never missed.
        for line in lines:
            match = self.DOWNLOAD_VERSION.match(line)
            if match and match.group(1) not in seen:
                seen.add(match.group(1))
                versions.append(ScrapedFirmware(version=match.group(1)))
                break

        for index, line in enumerate(lines):
            match = self.CHANGELOG_ENTRY.match(line)
            if not match:
                continue

            version, day, month, year = match.groups()
            try:
                release_date = datetime(int(year), int(month), int(day))
            except ValueError:
                release_date = None

            # The description runs until the next entry or the next version marker.
            description = []
            for following in lines[index + 1:]:
                if self.CHANGELOG_ENTRY.match(following) or self.DOWNLOAD_VERSION.match(following):
                    break
                description.append(following)
                if len(description) >= 3:
                    break

            if version in seen:
                # Already added from the download block, but now we have its date.
                for existing in versions:
                    if existing.version == version:
                        existing.release_date = existing.release_date or release_date
                        existing.changelog = existing.changelog or (" ".join(description)[:500] or None)
                continue

            seen.add(version)
            versions.append(
                ScrapedFirmware(
                    version=version,
                    release_date=release_date,
                    changelog=" ".join(description)[:500] or None,
                )
            )

        return versions

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        """Fetch versions from a TAL product page.

        The page is read first so the shipping version is always current. Anything
        in KNOWN_FIRMWARE that the page no longer lists is merged in afterwards as
        history -- TAL trims its changelog over time, and those entries were
        transcribed from this same page.
        """
        catalogue = self._catalogue or {}
        if device_name in catalogue:
            versions = [
                ScrapedFirmware(
                    version=fw.version, release_date=fw.release_date, changelog=fw.changelog
                )
                for fw in catalogue[device_name]["versions"]
            ]
        else:
            # A row the index no longer lists, or a scrape that did not list first.
            html = await self.fetch_page_js(firmware_page_url, wait_for_timeout=20000)
            versions = self._parse_changelog(html) if html else []

        if not versions and device_name not in self.KNOWN_FIRMWARE:
            return ScraperResult(
                success=False,
                error=f"No versions found for {device_name} at {firmware_page_url}",
            )

        seen = {fw.version for fw in versions}
        for version, date_str, changelog in self.KNOWN_FIRMWARE.get(device_name, []):
            if version in seen:
                continue
            try:
                release_date = datetime.strptime(date_str, "%Y-%m-%d")
            except (ValueError, TypeError):
                release_date = None
            seen.add(version)
            versions.append(
                ScrapedFirmware(
                    version=version,
                    release_date=release_date,
                    changelog=changelog,
                )
            )

        return ScraperResult(success=True, firmware_versions=versions)
