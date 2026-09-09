from datetime import datetime

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class NativeInstrumentsScraper(BaseScraper):
    """Scraper for Native Instruments plugins and software.

    NI distributes exclusively through Native Access — no public version
    info on their website. Uses hardcoded KNOWN_FIRMWARE data.
    """

    manufacturer_name = "Native Instruments"
    manufacturer_slug = "nativeinstruments"
    manufacturer_website = "https://www.native-instruments.com"

    KNOWN_FIRMWARE = {
        "Kontakt 8": [
            ("8.13.0", "2025-06-01", None),
        ],
        "Kontakt 7": [
            ("7.10.9", "2025-03-01", None),
        ],
        "Kontakt 6": [
            ("6.8.0", "2023-06-01", None),
        ],
        "Kontakt 5": [
            ("5.8.1", "2020-01-01", None),
        ],
        "Massive X": [
            ("1.7.1", "2025-03-01", None),
        ],
        "Massive": [
            ("1.7.0", "2024-06-01", None),
        ],
        "Reaktor 6": [
            ("6.5.0", "2024-01-01", None),
        ],
        "Absynth 5": [
            ("5.3.4", "2020-01-01", None),
        ],
        "Battery 4": [
            ("4.3.1", "2023-01-01", None),
        ],
        "FM8": [
            ("1.4.6", "2020-01-01", None),
        ],
        "Maschine 3": [
            ("3.6.0", "2025-06-01", None),
        ],
        "Maschine 2": [
            ("2.18.4", "2025-01-01", None),
        ],
        "Komplete Kontrol": [
            ("3.5.4", "2025-06-01", None),
        ],
        "Guitar Rig 7": [
            ("7.0.2", "2025-01-01", None),
        ],
        "Guitar Rig 6": [
            ("6.4.0", "2024-06-01", None),
        ],
        "Guitar Rig 5": [
            ("5.2.2", "2019-01-01", None),
        ],
        # Komplete effects bundled with Guitar Rig / Komplete
        "Bite": [
            ("1.3.7", "2025-01-01", None),
        ],
        "Choral": [
            ("1.3.7", "2025-01-01", None),
        ],
        "Dirt": [
            ("1.3.7", "2025-01-01", None),
        ],
        "Driver": [
            ("1.4.11", "2025-01-01", None),
        ],
        "Enhanced EQ": [
            ("1.4.12", "2025-06-01", None),
        ],
        "Flair": [
            ("1.3.7", "2025-01-01", None),
        ],
        "Freak": [
            ("1.3.7", "2025-01-01", None),
        ],
        "Passive EQ": [
            ("1.4.12", "2025-06-01", None),
        ],
        "Phasis": [
            ("1.3.7", "2025-01-01", None),
        ],
        "Raum": [
            ("1.3.7", "2025-01-01", None),
        ],
        "RC 24": [
            ("1.4.11", "2025-01-01", None),
        ],
        "RC 48": [
            ("1.4.11", "2025-01-01", None),
        ],
        "Replika": [
            ("1.6.7", "2025-01-01", None),
        ],
        "Replika XT": [
            ("1.3.7", "2025-01-01", None),
        ],
        "Solid Bus Comp": [
            ("1.4.11", "2025-01-01", None),
        ],
        "Solid Dynamics": [
            ("1.4.11", "2025-01-01", None),
        ],
        "Solid EQ": [
            ("1.4.11", "2025-01-01", None),
        ],
        "Supercharger GT": [
            ("1.4.11", "2025-01-01", None),
        ],
        "Transient Master": [
            ("1.4.11", "2025-01-01", None),
        ],
        "VC 76": [
            ("1.4.12", "2025-06-01", None),
        ],
        "VC 160": [
            ("1.4.11", "2025-01-01", None),
        ],
        "VC 2A": [
            ("1.4.11", "2025-01-01", None),
        ],
        "Vari Comp": [
            ("1.4.12", "2025-06-01", None),
        ],
    }

    KNOWN_PRODUCTS = [
        # Samplers & Synths
        ("Kontakt 8", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/samplers/kontakt/"),
        ("Kontakt 7", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/samplers/kontakt-7/"),
        ("Kontakt 6", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/samplers/kontakt-6/"),
        ("Kontakt 5", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/samplers/kontakt-5/"),
        ("Massive X", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/synths/massive-x/"),
        ("Massive", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/synths/massive/"),
        ("Reaktor 6", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/synths/reaktor-6/"),
        ("Absynth 5", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/synths/absynth-5/"),
        ("Battery 4", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/drums/battery-4/"),
        ("FM8", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/synths/fm8/"),
        # Production
        ("Maschine 3", "vst_plugin", "https://www.native-instruments.com/en/products/maschine/"),
        ("Maschine 2", "vst_plugin", "https://www.native-instruments.com/en/products/maschine/"),
        ("Komplete Kontrol", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/bundles/komplete-kontrol/"),
        # Guitar Rig
        ("Guitar Rig 7", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/guitar/guitar-rig-7-pro/"),
        ("Guitar Rig 6", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/guitar/guitar-rig-6-pro/"),
        ("Guitar Rig 5", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/guitar/guitar-rig-5-pro/"),
        # Komplete Effects
        ("Bite", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/effects/bite/"),
        ("Choral", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/effects/choral/"),
        ("Dirt", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/effects/dirt/"),
        ("Driver", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/effects/driver/"),
        ("Enhanced EQ", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/effects/enhanced-eq/"),
        ("Flair", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/effects/flair/"),
        ("Freak", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/effects/freak/"),
        ("Passive EQ", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/effects/passive-eq/"),
        ("Phasis", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/effects/phasis/"),
        ("Raum", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/effects/raum/"),
        ("RC 24", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/effects/rc-24/"),
        ("RC 48", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/effects/rc-48/"),
        ("Replika", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/effects/replika/"),
        ("Replika XT", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/effects/replika-xt/"),
        ("Solid Bus Comp", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/effects/solid-bus-comp/"),
        ("Solid Dynamics", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/effects/solid-dynamics/"),
        ("Solid EQ", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/effects/solid-eq/"),
        ("Supercharger GT", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/effects/supercharger-gt/"),
        ("Transient Master", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/effects/transient-master/"),
        ("VC 76", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/effects/vc-76/"),
        ("VC 160", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/effects/vc-160/"),
        ("VC 2A", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/effects/vc-2a/"),
        ("Vari Comp", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/effects/vari-comp/"),
    ]

    async def fetch_device_list(self) -> ScraperResult:
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

        return ScraperResult(success=True, firmware_versions=[])
