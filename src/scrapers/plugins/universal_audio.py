from datetime import datetime

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class UniversalAudioScraper(BaseScraper):
    """Scraper for Universal Audio UADX plugins.

    UA distributes exclusively through UA Connect — no public version
    info on their website. Uses hardcoded KNOWN_FIRMWARE data.
    """

    manufacturer_name = "Universal Audio"
    manufacturer_slug = "uaudio"
    manufacturer_website = "https://www.uaudio.com"

    KNOWN_FIRMWARE = {
        "Ampex ATR-102 Tape": [
            ("1.0.6", "2025-01-01", None),
        ],
        "Distressor": [
            ("1.0.9", "2025-01-01", None),
        ],
        "Dream Amp": [
            ("1.0.5", "2025-01-01", None),
        ],
        "Galaxy Tape Echo": [
            ("1.3.16", "2025-06-01", None),
        ],
        "Lion Amp": [
            ("1.0.5", "2025-01-01", None),
        ],
        "Polymax": [
            ("1.0.16", "2025-06-01", None),
        ],
        "Ruby Amp": [
            ("1.0.5", "2025-01-01", None),
        ],
        "Sound City Studios": [
            ("1.0.9", "2025-01-01", None),
        ],
        "Verve": [
            ("1.0.6", "2025-01-01", None),
        ],
        "Waterfall Rotary Speaker": [
            ("1.2.16", "2025-06-01", None),
        ],
    }

    # Map from plist CFBundleName to human-readable product name
    PLIST_NAME_MAP = {
        "uaudio_ampex_atr-102_tape": "Ampex ATR-102 Tape",
        "uaudio_distressor": "Distressor",
        "uaudio_dream_amp": "Dream Amp",
        "uaudio_galaxy_tape_echo": "Galaxy Tape Echo",
        "uaudio_lion_amp": "Lion Amp",
        "uaudio_polymax": "Polymax",
        "uaudio_ruby_amp": "Ruby Amp",
        "uaudio_sound_city_studios": "Sound City Studios",
        "uaudio_verve": "Verve",
        "uaudio_waterfall_rotary_speaker": "Waterfall Rotary Speaker",
    }

    KNOWN_PRODUCTS = [
        ("Ampex ATR-102 Tape", "vst_plugin", "https://www.uaudio.com/uad-plugins/mastering/ampex-atr-102.html"),
        ("Distressor", "vst_plugin", "https://www.uaudio.com/uad-plugins/compressors-limiters/empirical-labs-distressor.html"),
        ("Dream Amp", "vst_plugin", "https://www.uaudio.com/uad-plugins/guitar-bass/dream-65.html"),
        ("Galaxy Tape Echo", "vst_plugin", "https://www.uaudio.com/uad-plugins/delay/galaxy-tape-echo.html"),
        ("Lion Amp", "vst_plugin", "https://www.uaudio.com/uad-plugins/guitar-bass/lion-68.html"),
        ("Polymax", "vst_plugin", "https://www.uaudio.com/uad-plugins/instruments/polymax-synth.html"),
        ("Ruby Amp", "vst_plugin", "https://www.uaudio.com/uad-plugins/guitar-bass/ruby-63.html"),
        ("Sound City Studios", "vst_plugin", "https://www.uaudio.com/uad-plugins/reverbs/sound-city-studios.html"),
        ("Verve", "vst_plugin", "https://www.uaudio.com/uad-plugins/instruments/verve-analog-machines.html"),
        ("Waterfall Rotary Speaker", "vst_plugin", "https://www.uaudio.com/uad-plugins/modulation/waterfall-rotary-speaker.html"),
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
