import re
from datetime import datetime

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class TALScraper(BaseScraper):
    """Scraper for TAL Software (Togu Audio Line) virtual instruments."""

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

    # Known TAL products
    KNOWN_PRODUCTS = [
        ("TAL-U-NO-LX-V2", "vst_plugin", "https://tal-software.com/products/tal-u-no-lx"),
        ("TAL-J-8", "vst_plugin", "https://tal-software.com/products/tal-j-8"),
        ("TAL-Sampler", "vst_plugin", "https://tal-software.com/products/tal-sampler"),
        ("TAL-MOD", "vst_plugin", "https://tal-software.com/products/tal-mod"),
        ("TAL-DAC", "vst_plugin", "https://tal-software.com/products/tal-dac"),
        ("TAL-Drum", "vst_plugin", "https://tal-software.com/products/tal-drum"),
        ("TAL-BassLine-101", "vst_plugin", "https://tal-software.com/products/tal-bassline-101"),
        ("TAL-NoiseMaker", "vst_plugin", "https://tal-software.com/products/tal-noisemaker"),
        ("TAL-Reverb-4", "vst_plugin", "https://tal-software.com/products/tal-reverb-4"),
    ]

    async def fetch_device_list(self) -> ScraperResult:
        """Return the list of known TAL products."""
        devices = [
            ScrapedDevice(
                name=name,
                category=category,
                firmware_page_url=url,
                product_url=url,
            )
            for name, category, url in self.KNOWN_PRODUCTS
        ]
        return ScraperResult(success=True, devices=devices)

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        """Fetch versions from a TAL product page."""
        # Use known firmware data for products with JS-loaded changelogs
        if device_name in self.KNOWN_FIRMWARE:
            firmware_versions = []
            for version, date_str, changelog in self.KNOWN_FIRMWARE[device_name]:
                try:
                    release_date = datetime.strptime(date_str, "%Y-%m-%d")
                except ValueError:
                    release_date = None
                firmware_versions.append(
                    ScrapedFirmware(
                        version=version,
                        release_date=release_date,
                        changelog=changelog,
                    )
                )
            return ScraperResult(success=True, firmware_versions=firmware_versions)

        # TAL pages use JavaScript to load changelog - try Playwright first
        html = await self.fetch_page_js(firmware_page_url, wait_for_timeout=10000)
        # Fall back to static fetch if JS fetch fails
        if not html:
            html = await self.fetch_page(firmware_page_url)
        if not html:
            return ScraperResult(
                success=False, error=f"Failed to fetch {firmware_page_url}"
            )

        soup = self.parse_html(html)
        firmware_versions = []
        all_text = soup.get_text()

        # TAL versions look like "v5.1.3" or "Version 2.0.4"
        version_pattern = r"[Vv](?:ersion)?\s*(\d+\.\d+(?:\.\d+)?)"

        # TAL product pages typically have version info and changelog
        # Look for version/changelog sections
        sections = soup.find_all(
            ["div", "section", "p", "span", "td", "li", "article"],
            class_=re.compile(r"version|changelog|update|download|info|content", re.I)
        )

        # Also look for download buttons/links
        download_sections = soup.find_all(
            ["div", "a"],
            class_=re.compile(r"download|button", re.I)
        )

        for section in sections + download_sections:
            text = section.get_text()
            version_match = re.search(version_pattern, text)

            if version_match:
                version = version_match.group(1)

                # Find download link
                download_link = section.find("a", href=re.compile(r"\.(dmg|pkg|exe|zip|vst)", re.I))
                if not download_link:
                    download_link = section.find_parent("a")
                download_url = None
                if download_link and download_link.get("href"):
                    download_url = download_link["href"]
                    if not download_url.startswith("http"):
                        download_url = f"https://tal-software.com{download_url}"

                # TAL uses dates like "29.12.2025" (DD.MM.YYYY)
                date_patterns = [
                    (r"(\d{1,2})\.(\d{1,2})\.(\d{4})", "dmy"),  # DD.MM.YYYY
                    (r"(\d{1,2})/(\d{1,2})/(\d{4})", "mdy"),   # MM/DD/YYYY
                    (r"(\w+)\s+(\d{4})", "month_year"),         # Month YYYY
                ]
                release_date = None
                for pattern, fmt_type in date_patterns:
                    date_match = re.search(pattern, text)
                    if date_match:
                        try:
                            if fmt_type == "dmy":
                                day, month, year = date_match.groups()
                                release_date = datetime(int(year), int(month), int(day))
                            elif fmt_type == "mdy":
                                month, day, year = date_match.groups()
                                release_date = datetime(int(year), int(month), int(day))
                            elif fmt_type == "month_year":
                                month_str, year = date_match.groups()
                                release_date = datetime.strptime(f"{month_str} {year}", "%B %Y")
                            break
                        except ValueError:
                            continue

                # Get changelog text
                changelog = None
                changelog_section = section.find(
                    ["ul", "div", "p"],
                    class_=re.compile(r"changelog|changes|notes", re.I)
                )
                if changelog_section:
                    changelog = changelog_section.get_text(strip=True)[:500]

                firmware_versions.append(
                    ScrapedFirmware(
                        version=version,
                        release_date=release_date,
                        download_url=download_url,
                        changelog=changelog,
                    )
                )

        # Fallback: scan entire page for version strings
        if not firmware_versions:
            matches = re.findall(version_pattern, all_text)
            seen = set()
            for version in matches:
                if version not in seen:
                    seen.add(version)
                    firmware_versions.append(ScrapedFirmware(version=version))

        # Deduplicate
        seen = set()
        unique = []
        for fw in firmware_versions:
            if fw.version not in seen:
                seen.add(fw.version)
                unique.append(fw)

        return ScraperResult(success=True, firmware_versions=unique)
