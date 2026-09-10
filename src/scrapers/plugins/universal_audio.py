from src.scrapers.base import BaseScraper, ScrapedDevice, ScraperResult


class UniversalAudioScraper(BaseScraper):
    """Universal Audio UADX plugins, whose versions are not published anywhere public.

    This scraper deliberately reports no firmware versions. That is the finding, not
    a gap waiting to be filled, so the search below is written down to save the next
    person repeating it (checked 2026-09-10):

    - `help.uaudio.com` runs Zendesk and its Help Center API answers fine. There is a
      "UAD Native Plug-Ins Release Notes" article, which sounds exactly right and is
      not. It groups changes by month, names the plugins that changed, and gives no
      version numbers at all -- the only version-shaped strings in it are DAW versions
      like "Pro Tools 2025.6". Two of the ten products here are mentioned; the rest
      never appear.
    - UA Connect fetches `external-content.db` from S3, which would be the manifest.
      It is an encrypted blob.
    - `plugins.uaudio.com` returns 403 for everything, including a slug made up to
      test it, so its refusal says nothing about what exists.
    - Every `uaudio.com` release-notes path 404s, confirmed against a control URL that
      returned byte-identical content.

    The previous version of this file carried a `KNOWN_FIRMWARE` table, and the
    problem with it was worse than going stale. Its ten entries matched the versions
    installed on the developer's own machine exactly, because that is where they came
    from. So it reported every UA plugin as up to date by construction, could never
    report anything else, and paired each version with an invented release date. The
    app's whole purpose is to say when an update is waiting; for these plugins it
    cannot, and saying so is more useful than a permanent green tick.

    Devices therefore land in `devices_without_firmware`, show as "Firmware Unknown"
    on the dashboard, and link to UA's release notes so the check can be done by hand.
    """

    manufacturer_name = "Universal Audio"
    manufacturer_slug = "uaudio"
    manufacturer_website = "https://www.uaudio.com"

    # The closest thing UA has to a firmware page. It carries no versions, but it is
    # where a human would look, so it is what the device's "Details" link should open.
    RELEASE_NOTES_URL = (
        "https://help.uaudio.com/hc/en-us/articles/"
        "32181404310420-UAD-Native-Plug-Ins-Release-Notes"
    )

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
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category=category,
                    # firmware_page_url is what a device's "Details" link opens, so it
                    # points at the release notes rather than the shop page.
                    firmware_page_url=self.RELEASE_NOTES_URL,
                    product_url=url,
                )
                for name, category, url in self.KNOWN_PRODUCTS
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        """Succeed while reporting nothing, because nothing is what UA publishes.

        This is success, not failure: the fetch did not break, the product simply has
        no discoverable version. The service keeps those apart -- `devices_failed`
        against `devices_without_firmware` -- and conflating them would either hide a
        real breakage or raise a false alarm every run.
        """
        return ScraperResult(success=True, firmware_versions=[])
