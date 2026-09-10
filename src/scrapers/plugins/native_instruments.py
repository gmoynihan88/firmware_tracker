import re

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class NativeInstrumentsScraper(BaseScraper):
    """Scraper for Native Instruments plugins and software.

    NI distributes exclusively through Native Access — no public version
    info on their website. Uses hardcoded KNOWN_FIRMWARE data.
    """

    manufacturer_name = "Native Instruments"
    manufacturer_slug = "nativeinstruments"
    manufacturer_website = "https://www.native-instruments.com"

    # NI maintains a per-product "Official update status" thread whose title carries
    # the current version, e.g. "Official update status - Kontakt (current version:
    # 8.13.0)". The numeric discussion id is stable even though the URL slug goes
    # stale, so the id is what we key on. These are the live-tracked products.
    UPDATE_THREAD_URL = "https://community.native-instruments.com/discussion/{thread_id}"

    UPDATE_THREADS = {
        "Kontakt 8": 39,
        "Maschine 3": 40,
        "Guitar Rig 7": 53,
        "Massive X": 54,
        "Komplete Kontrol": 55,
        "Reaktor 6": 56,
        "Absynth 6": 49105,
        "Massive": 7093,
    }

    # Superseded products. NI no longer ships updates for these, so the version is
    # genuinely fixed rather than merely unchecked -- each was replaced by a major
    # release that is tracked live above.
    SUPERSEDED_VERSIONS = {
        "Kontakt 7": "7.10.9",
        "Kontakt 6": "6.8.0",
        "Kontakt 5": "5.8.1",
        "Absynth 5": "5.3.4",
        "Guitar Rig 6": "6.4.0",
        "Guitar Rig 5": "5.2.2",
        "Maschine 2": "2.18.4",
    }

    # Current products with no public version source. NI ships these through Native
    # Access only and publishes no update thread for them, so these values are a
    # best effort and can go stale without anything noticing. Their changelog text
    # says so, so an unverified value is distinguishable from a real lookup.
    UNVERIFIED_VERSIONS = {
        "Battery 4": "4.3.1",
        "FM8": "1.4.6",
        # Effects ship as a bundle, hence the shared version numbers.
        "Bite": "1.3.7", "Choral": "1.3.7", "Dirt": "1.3.7", "Flair": "1.3.7",
        "Freak": "1.3.7", "Phasis": "1.3.7", "Raum": "1.3.7", "Replika XT": "1.3.7",
        "Replika": "1.6.7",
        "Driver": "1.4.11", "RC 24": "1.4.11", "RC 48": "1.4.11",
        "Solid Bus Comp": "1.4.11", "Solid Dynamics": "1.4.11", "Solid EQ": "1.4.11",
        "Supercharger GT": "1.4.11", "Transient Master": "1.4.11",
        "VC 160": "1.4.11", "VC 2A": "1.4.11",
        "Enhanced EQ": "1.4.12", "Passive EQ": "1.4.12", "VC 76": "1.4.12",
        "Vari Comp": "1.4.12",
    }

    TITLE_VERSION = re.compile(
        r"Official update status\s*-\s*(?P<product>.+?)\s*"
        r"\(current version:?\s*(?P<version>[^)]+)\)",
        re.I,
    )

    KNOWN_PRODUCTS = [
        # Samplers & Synths
        ("Kontakt 8", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/samplers/kontakt/"),
        ("Kontakt 7", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/samplers/kontakt-7/"),
        ("Kontakt 6", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/samplers/kontakt-6/"),
        ("Kontakt 5", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/samplers/kontakt-5/"),
        ("Massive X", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/synths/massive-x/"),
        ("Massive", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/synths/massive/"),
        ("Reaktor 6", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/synths/reaktor-6/"),
        ("Absynth 6", "vst_plugin", "https://www.native-instruments.com/en/products/komplete/synths/absynth/"),
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
        """Resolve a product's current version.

        Live-tracked products are read from their update thread. Superseded and
        unverified products fall back to a static value, each labelled in the
        changelog so the provenance is visible downstream.
        """
        thread_id = self.UPDATE_THREADS.get(device_name)
        if thread_id is not None:
            return await self._fetch_from_thread(device_name, thread_id)

        version = self.SUPERSEDED_VERSIONS.get(device_name)
        if version:
            return ScraperResult(
                success=True,
                firmware_versions=[
                    ScrapedFirmware(
                        version=version,
                        changelog="Superseded product; NI no longer ships updates.",
                    )
                ],
            )

        version = self.UNVERIFIED_VERSIONS.get(device_name)
        if version:
            return ScraperResult(
                success=True,
                firmware_versions=[
                    ScrapedFirmware(
                        version=version,
                        changelog=(
                            "Unverified: NI publishes no publicly checkable version "
                            "for this product. May be out of date."
                        ),
                    )
                ],
            )

        return ScraperResult(
            success=False,
            error=f"No version source configured for {device_name}",
        )

    async def _fetch_from_thread(self, device_name: str, thread_id: int) -> ScraperResult:
        """Read the current version out of an update thread's title."""
        url = self.UPDATE_THREAD_URL.format(thread_id=thread_id)
        html = await self.fetch_page_js(url, wait_for_timeout=25000)
        if not html:
            return ScraperResult(
                success=False,
                error=f"Failed to fetch update thread {thread_id} for {device_name}",
            )

        soup = self.parse_html(html)
        title = soup.title.get_text() if soup.title else ""
        match = self.TITLE_VERSION.search(title)
        if not match:
            return ScraperResult(
                success=False,
                error=(
                    f"Update thread {thread_id} for {device_name} did not carry a "
                    f"version in its title: {title[:80]!r}"
                ),
            )

        return ScraperResult(
            success=True,
            firmware_versions=[
                ScrapedFirmware(
                    version=match.group("version").strip(),
                    download_url=url,
                    changelog=f"Reported by NI as current for {match.group('product').strip()}.",
                )
            ],
        )
