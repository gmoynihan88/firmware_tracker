import re
from datetime import datetime
from typing import List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class ModarttScraper(BaseScraper):
    """Scraper for Modartt virtual instruments (Pianoteq)."""

    manufacturer_name = "Modartt"
    manufacturer_slug = "modartt"
    manufacturer_website = "https://www.modartt.com"

    # Known firmware versions (changelog is JS-loaded)
    KNOWN_FIRMWARE = {
        "Pianoteq 8": [
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
            ("8.4.0", "2024-11-05", "New Grand Shigeru Kawai SK-EX."),
            ("8.3.0", "2024-06-11", "New Grand Bosendorfer 280VC."),
            ("8.2.0", "2024-01-14", "Revoicing of all 11 modern grand pianos."),
            ("8.0.0", "2022-11-15", "New Classical Guitar model. All pianos revoiced."),
        ],
        "Pianoteq 8 Standard": [
            ("8.4.0", "2024-11-05", "New Grand Shigeru Kawai SK-EX."),
            ("8.3.0", "2024-06-11", "New Grand Bosendorfer 280VC."),
            ("8.2.0", "2024-01-14", "Revoicing of all 11 modern grand pianos."),
            ("8.0.0", "2022-11-15", "New Classical Guitar model. All pianos revoiced."),
        ],
        "Pianoteq 8 Pro": [
            ("8.4.0", "2024-11-05", "New Grand Shigeru Kawai SK-EX."),
            ("8.3.0", "2024-06-11", "New Grand Bosendorfer 280VC."),
            ("8.2.0", "2024-01-14", "Revoicing of all 11 modern grand pianos."),
            ("8.0.0", "2022-11-15", "New Classical Guitar model. All pianos revoiced. New stretch points note-edit."),
        ],
        "Pianoteq 9": [
            ("9.2.4", "2026-08-01", None),
            ("9.1.0", "2025-12-09", "New instrument pack: Syngular. New Warm, Mono and Binaural presets. Next/previous favourite preset shortcuts."),
            ("9.0.3", "2025-11-16", "Workaround for sustain pedal issues in some DAWs. Fix mics 6,7,8 distortion. Fix VST3 bundle folder attributes."),
            ("9.0.2", "2025-10-19", "Fix STAGE version multi-instance issue in Logic. Fix VST3 automation. Added Binaural and Under Lid presets."),
            ("9.0.1", "2025-10-14", "iOS Dark mode support for app icon."),
            ("9.0.0", "2025-10-14", "New Triple Harp instrument. Grand pianos updated. Up to 8 mics. VST3 on Linux. NKS2 support. Thunder pedal."),
        ],
        "Pianoteq 9 Stage": [
            ("9.2.4", "2026-08-01", None),
            ("9.1.0", "2025-12-09", "New instrument pack: Syngular. New presets added to grand pianos."),
            ("9.0.0", "2025-10-14", "New Triple Harp. STAGE users can now access Mics & Mix panel."),
        ],
        "Pianoteq 9 Standard": [
            ("9.2.4", "2026-08-01", None),
            ("9.1.0", "2025-12-09", "New instrument pack: Syngular. New presets added to grand pianos."),
            ("9.0.0", "2025-10-14", "New Triple Harp. Up to 8 mics. NKS2 support."),
        ],
        "Pianoteq 9 Pro": [
            ("9.2.4", "2026-08-01", None),
            ("9.1.0", "2025-12-09", "New instrument pack: Syngular. New presets added to grand pianos."),
            ("9.0.0", "2025-10-14", "New Triple Harp. Up to 8 mics. NKS2 support. Hammer Tone note-edit."),
        ],
    }

    # Known Modartt products
    KNOWN_PRODUCTS = [
        ("Pianoteq 8", "vst_plugin", "https://www.modartt.com/pianoteq_overview"),
        ("Pianoteq 8 Stage", "vst_plugin", "https://www.modartt.com/pianoteq_overview"),
        ("Pianoteq 8 Standard", "vst_plugin", "https://www.modartt.com/pianoteq_overview"),
        ("Pianoteq 8 Pro", "vst_plugin", "https://www.modartt.com/pianoteq_overview"),
        ("Pianoteq 9", "vst_plugin", "https://www.modartt.com/pianoteq_overview"),
        ("Pianoteq 9 Stage", "vst_plugin", "https://www.modartt.com/pianoteq_overview"),
        ("Pianoteq 9 Standard", "vst_plugin", "https://www.modartt.com/pianoteq_overview"),
        ("Pianoteq 9 Pro", "vst_plugin", "https://www.modartt.com/pianoteq_overview"),
    ]

    # The /pianoteq_changes page renders nothing server-side; its content is loaded
    # from this endpoint, which returns {"maj": 9, "min": 25, "html": "<changelog>"}.
    # maj/min give the shipping release (9.2.5 here) and html the dated history.
    PRODUCTS_API = "https://www.modartt.com/api/0/products"
    PRODUCTS_PAYLOAD = {"action": "changelog", "software": "pianoteq"}

    # Changelog entries look like: <div class="mrt-title">9.2.5 (2026/09/09)</div>
    CHANGELOG_TITLE = re.compile(
        r"^\s*(\d+(?:\.\d+)+)\s*\((\d{4})/(\d{1,2})/(\d{1,2})\)"
    )

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

    def _major_version_prefix(self, device_name: str) -> str:
        """Extract major version prefix from device name: 'Pianoteq 8 Pro' -> '8.'."""
        m = re.search(r"(\d+)", device_name)
        return f"{m.group(1)}." if m else "8."

    async def _fetch_products_payload(self) -> Optional[dict]:
        """Fetch the JSON payload backing the changelog page."""
        return await self.fetch_json(
            self.PRODUCTS_API, method="POST", json_body=self.PRODUCTS_PAYLOAD
        )

    def _parse_changelog(self, html: str) -> List[ScrapedFirmware]:
        """Parse the dated version list out of the changelog markup.

        Only the title divs are read. Scanning raw text picks up version-like
        strings from the descriptions themselves (an OS version, say) that are not
        Pianoteq releases at all.
        """
        soup = self.parse_html(html)
        versions = []

        for title in soup.find_all("div", class_="mrt-title"):
            match = self.CHANGELOG_TITLE.match(title.get_text(" ", strip=True))
            if not match:
                continue

            version, year, month, day = match.groups()
            try:
                release_date = datetime(int(year), int(month), int(day))
            except ValueError:
                release_date = None

            body = title.find_next_sibling()
            changelog = body.get_text(" ", strip=True)[:500] if body else None

            versions.append(
                ScrapedFirmware(
                    version=version,
                    release_date=release_date,
                    changelog=changelog or None,
                )
            )

        return versions

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        """Fetch Pianoteq versions for the edition's major release.

        Every edition of a major version -- Stage, Standard, Pro -- ships the same
        build, so they share the changelog and differ only in unlocked features.
        """
        prefix = self._major_version_prefix(device_name)

        payload = await self._fetch_products_payload()
        if payload:
            versions = [
                fw for fw in self._parse_changelog(payload.get("html", ""))
                if fw.version.startswith(prefix)
            ]

            # maj/min name the shipping build, which can lead the changelog.
            maj, minor = payload.get("maj"), payload.get("min")
            if isinstance(maj, int) and isinstance(minor, int) and str(maj) == prefix.rstrip("."):
                current = f"{maj}.{minor // 10}.{minor % 10}"
                if not any(fw.version == current for fw in versions):
                    versions.insert(0, ScrapedFirmware(version=current))

            if versions:
                return ScraperResult(success=True, firmware_versions=versions)

        # The API is the only source that carries real versions, so a failure here
        # is a failure -- falling back to a static table is how this went stale.
        return ScraperResult(
            success=False,
            error=f"Could not read Pianoteq versions for {device_name} from {self.PRODUCTS_API}",
        )
