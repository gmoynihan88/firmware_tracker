import re
from datetime import datetime
from typing import Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class ModarttScraper(BaseScraper):
    """Scraper for Modartt virtual instruments (Pianoteq)."""

    manufacturer_name = "Modartt"
    manufacturer_slug = "modartt"
    manufacturer_website = "https://www.modartt.com"

    # Known firmware versions (changelog is JS-loaded)
    KNOWN_FIRMWARE = {
        "Pianoteq 8": [
            ("9.1.0", "2025-12-09", "New instrument pack: Syngular. New Warm, Mono and Binaural presets. Next/previous favourite preset shortcuts."),
            ("9.0.3", "2025-11-16", "Workaround for sustain pedal issues in some DAWs. Fix mics 6,7,8 distortion. Fix VST3 bundle folder attributes."),
            ("9.0.2", "2025-10-19", "Fix STAGE version multi-instance issue in Logic. Fix VST3 automation. Added Binaural and Under Lid presets."),
            ("9.0.1", "2025-10-14", "iOS Dark mode support for app icon."),
            ("9.0.0", "2025-10-14", "New Triple Harp instrument. Grand pianos updated. Up to 8 mics. VST3 on Linux. NKS2 support. Thunder pedal."),
            ("8.4.3", "2025-06-12", "Fix crashes on startup. Fix performance issues with Intel CPUs."),
            ("8.4.2", "2025-06-01", "iOS: Improve error reporting when appstore purchase fails."),
            ("8.4.1", "2025-02-03", "Fix performance issue with Kawai SK-EX on Intel CPUs."),
            ("8.4.0", "2024-11-05", "New Grand Shigeru Kawai SK-EX. New M49 tube microphone."),
            ("8.3.2", "2024-09-22", "Added touchscreen option. Fixed audio buffer size on iOS 18."),
            ("8.3.1", "2024-06-24", "Fixed lingering resonances. Grand Bosendorfer 280VC fixes."),
            ("8.3.0", "2024-06-11", "New Grand Bosendorfer 280VC. MIDI demos in presets. Gain reduction meter."),
            ("8.2.2", "2024-04-23", "Fix microtuning with VST3 in Dorico."),
            ("8.2.1", "2024-04-08", "Fix pedal noise issue with some instruments."),
            ("8.2.0", "2024-01-14", "Revoicing of all 11 modern grand pianos. Fret buzz for Classical Guitar."),
            ("8.1.3", "2023-08-09", "Fixed pitch-bend MIDI channel issues. Max pitch-bend range increased to 4800 cents."),
            ("8.1.2", "2023-06-02", "iOS: roll back popup menu changes."),
            ("8.1.1", "2023-06-01", "Fix random deadlock when loading multiple instances."),
            ("8.1.0", "2023-05-14", "Hammer noise low frequency content improved."),
            ("8.0.9", "2023-05-02", "iOS version released."),
            ("8.0.8", "2023-04-02", "Fix broken record button. Fix parameter update issues."),
            ("8.0.7", "2023-03-28", "Workaround for Logic Pro crashes on M1/M2. Note naming changed to Scientific pitch notation."),
            ("8.0.6", "2023-03-26", "AAX plugin compatible with Pro Tools 2023.3. Lower CPU when idle."),
            ("8.0.5", "2022-12-21", "Fixed rare crash on plugin instantiation."),
            ("8.0.4", "2022-12-19", "Glissando pedal switch added. Fix crash during midi-learn."),
            ("8.0.3", "2022-12-07", "Fix crash when randomizing morphing/layers. Improved touch screen response."),
            ("8.0.2", "2022-11-23", "Fixed Monophonic output in FL Studio. Fixed Giusti harpsichord key switches."),
            ("8.0.1", "2022-11-18", "Fixed accessibility issue. Fixed channels selection on macOS."),
            ("8.0.0", "2022-11-15", "New Classical Guitar model. All pianos revoiced. New Note Effects panel. LV2/VST3/AU audio input support."),
        ],
        "Pianoteq 8 Stage": [
            ("9.1.0", "2025-12-09", "New instrument pack: Syngular. New presets added to grand pianos."),
            ("9.0.0", "2025-10-14", "New Triple Harp. STAGE users can now access Mics & Mix panel."),
            ("8.4.0", "2024-11-05", "New Grand Shigeru Kawai SK-EX."),
            ("8.3.0", "2024-06-11", "New Grand Bosendorfer 280VC."),
            ("8.2.0", "2024-01-14", "Revoicing of all 11 modern grand pianos."),
            ("8.0.0", "2022-11-15", "New Classical Guitar model. All pianos revoiced."),
        ],
        "Pianoteq 8 Standard": [
            ("9.1.0", "2025-12-09", "New instrument pack: Syngular. New presets added to grand pianos."),
            ("9.0.0", "2025-10-14", "New Triple Harp. Up to 8 mics. NKS2 support."),
            ("8.4.0", "2024-11-05", "New Grand Shigeru Kawai SK-EX."),
            ("8.3.0", "2024-06-11", "New Grand Bosendorfer 280VC."),
            ("8.2.0", "2024-01-14", "Revoicing of all 11 modern grand pianos."),
            ("8.0.0", "2022-11-15", "New Classical Guitar model. All pianos revoiced."),
        ],
        "Pianoteq 8 Pro": [
            ("9.1.0", "2025-12-09", "New instrument pack: Syngular. New presets added to grand pianos."),
            ("9.0.0", "2025-10-14", "New Triple Harp. Up to 8 mics. NKS2 support. Hammer Tone note-edit."),
            ("8.4.0", "2024-11-05", "New Grand Shigeru Kawai SK-EX."),
            ("8.3.0", "2024-06-11", "New Grand Bosendorfer 280VC."),
            ("8.2.0", "2024-01-14", "Revoicing of all 11 modern grand pianos."),
            ("8.0.0", "2022-11-15", "New Classical Guitar model. All pianos revoiced. New stretch points note-edit."),
        ],
    }

    # Known Modartt products
    KNOWN_PRODUCTS = [
        ("Pianoteq 8", "vst_plugin", "https://www.modartt.com/pianoteq_overview"),
        ("Pianoteq 8 Stage", "vst_plugin", "https://www.modartt.com/pianoteq_overview"),
        ("Pianoteq 8 Standard", "vst_plugin", "https://www.modartt.com/pianoteq_overview"),
        ("Pianoteq 8 Pro", "vst_plugin", "https://www.modartt.com/pianoteq_overview"),
    ]

    # Public page for version history
    VERSION_HISTORY_URL = "https://www.modartt.com/pianoteq_changes"
    DOWNLOAD_PAGE_URL = "https://www.modartt.com/download"

    async def fetch_device_list(self) -> ScraperResult:
        """Return the list of known Modartt products."""
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
        """Fetch Pianoteq versions from the download/overview page."""
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

        # Try the download page first as it typically has version info
        html = await self.fetch_page(self.DOWNLOAD_PAGE_URL)
        if not html:
            html = await self.fetch_page(firmware_page_url)
        if not html:
            return ScraperResult(
                success=False, error=f"Failed to fetch version info"
            )

        soup = self.parse_html(html)
        firmware_versions = []
        all_text = soup.get_text()

        # Pianoteq versions look like "8.2.1" or "Pianoteq 8.2.1"
        version_pattern = r"(?:Pianoteq\s+)?(\d+\.\d+(?:\.\d+)?)"

        # Look for download sections or version info
        sections = soup.find_all(
            ["div", "section", "p", "td"],
            class_=re.compile(r"download|version|release|update", re.I)
        )

        for section in sections:
            text = section.get_text()
            version_match = re.search(version_pattern, text)

            if version_match:
                version = version_match.group(1)

                # Find download link
                download_link = section.find("a", href=re.compile(r"\.(dmg|pkg|exe|zip)", re.I))
                download_url = download_link["href"] if download_link else None
                if download_url and not download_url.startswith("http"):
                    download_url = f"https://www.modartt.com{download_url}"

                # Look for date
                date_pattern = r"(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\w+\s+\d{1,2},?\s+\d{4})"
                date_match = re.search(date_pattern, text)
                release_date = None
                if date_match:
                    date_str = date_match.group(1)
                    for fmt in ["%m/%d/%Y", "%d/%m/%Y", "%B %d, %Y", "%B %d %Y"]:
                        try:
                            release_date = datetime.strptime(date_str.replace(",", ""), fmt)
                            break
                        except ValueError:
                            continue

                firmware_versions.append(
                    ScrapedFirmware(
                        version=version,
                        release_date=release_date,
                        download_url=download_url,
                        changelog=text.strip()[:500] if text else None,
                    )
                )

        # Fallback: extract any version numbers from page
        if not firmware_versions:
            # Look specifically for "Pianoteq X.X.X" patterns
            matches = re.findall(r"Pianoteq\s+(\d+\.\d+(?:\.\d+)?)", all_text)
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
