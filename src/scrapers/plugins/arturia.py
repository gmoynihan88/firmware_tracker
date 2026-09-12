import json
import re
from datetime import datetime
from typing import Dict, List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class ArturiaScraper(BaseScraper):
    """Arturia, read from the two JSON endpoints its own downloads page calls.

    The downloads page renders "No Results Found" server-side and fills itself in
    from `/api/content/products`. That endpoint has a sibling, `/api/content/resources`,
    which returns every downloadable Arturia has ever published -- 7,121 records -- in
    one request. Between them the whole catalogue costs two fetches rather than one per
    product, which matters here more than for most vendors: 184 products would
    otherwise be 184 page loads.

    A resource record is already the shape this scraper needs:

        {"type": "firmware", "product_id": 295, "product_name": "MicroFreak",
         "version": "4.0.3.1625", "release_date": "2022-06-15T12:00:00.000+00:00",
         "permalink": "https://dl.arturia.net/.../MicroFreak_Firmware_Update_4_0_3_1625.mff"}

    `type` is what separates the firmware from everything sitting beside it, and it
    does the job that wording on an HTML page usually has to. Of the 7,121 records,
    1,557 are `manual` -- the "User Guide V4" false positive, pre-labelled -- and 4,103
    are `soft`, the desktop software. On the MiniFreak's own page the hardware reads
    "Version 4.0.1" and the MiniFreak V editor reads "Version 4.0.2.6369", the
    companion-app trap in its usual form; here they are simply different `type` and
    different `product_id`.

    **Every record carries a release date.** 270 of 270 firmware records and 4,103 of
    4,103 software records, with one to ten versions per product and a median of three.
    That is the best-dated source in this project.

    Three things about the data that a straightforward reading gets wrong:

    - **`latest` is per platform, not per product.** KeyLab 88 has three records
      flagged `latest`: version 1.2.0.6 with no platform, and 1.1.0.4 for each of mac
      and windows. Believing the flag reports a version two releases stale. The flag is
      therefore ignored entirely -- `ScraperService` already picks the newest by
      version tuple, the same way it does for every other vendor.
    - **Two products can be the same product.** Two entries are called AudioFuse,
      generation 0 and generation 2. They are one interface: same firmware name, same
      versions, except the older entry carries the full history (1.0.4 through 1.2.3)
      and the newer one only the current release. Devices are keyed by name and their
      resources merged, so this reads as one device with four versions rather than two
      devices, one of which has no history.
    - **Platform builds of one version can differ by a day.** 51 of 2,055 software
      versions are dated one day apart on mac and windows. The earliest is kept: the
      release is when it first shipped, not when the last build finished.

    Scope is 184 products: 68 hardware with firmware, 116 software instruments and
    effects. The 410 preset packs, 50 bundles and 427 in-app purchases are excluded --
    they are content rather than products with a firmware line, and `product_type`
    names them. Every product included reports a real version with a real date, which
    is the test that keeps a catalogue worth reading: Focusrite contributes 28 rows
    that will never say anything, and none of these are that.
    """

    manufacturer_name = "Arturia"
    manufacturer_slug = "arturia"
    manufacturer_website = "https://www.arturia.com"

    PRODUCTS_API = "https://www.arturia.com/api/content/products"
    RESOURCES_API = "https://www.arturia.com/api/content/resources"

    # Hardware takes firmware; software takes installers. Anything else Arturia sells
    # -- PresetPack, SoftwareBundle, ExpansionPack, 3rdpartyLicence, IOS, Utility --
    # has no firmware line of its own.
    HARDWARE_TYPES = {
        "MIDIKeyboard": "midi_controller",
        "Sequencer": "midi_controller",
        "HardwareSynth": "synthesizer",
        "DigitalDrum": "synthesizer",
        "DrumMachine": "synthesizer",
        "AudioInterface": "audio_interface",
    }
    SOFTWARE_TYPES = {
        "SoftwareInstrument": "vst_plugin",
        "SoftwareFX": "vst_plugin",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._devices: Optional[Dict[str, dict]] = None

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(part) for part in re.findall(r"\d+", version or "")) or (0,)

    @staticmethod
    def _parse_date(value: Optional[str]) -> Optional[datetime]:
        """Read "2022-06-15T12:00:00.000+00:00".

        Stored without the timezone, because every other date in this database is
        naive and a mixture sorts unpredictably.
        """
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None

    async def _fetch_json(self, url: str):
        raw = await self.fetch_page(url)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return None

    async def _load(self) -> Optional[Dict[str, dict]]:
        """Build the catalogue from the two endpoints. Cached for the run."""
        if self._devices is not None:
            return self._devices

        products = await self._fetch_json(self.PRODUCTS_API)
        if not products:
            return None
        resources = await self._fetch_json(self.RESOURCES_API)
        if not resources:
            return None

        wanted: Dict[int, dict] = {}
        for product in products:
            product_type = product.get("product_type")
            category = self.HARDWARE_TYPES.get(product_type) or self.SOFTWARE_TYPES.get(product_type)
            if not category:
                continue
            product_id = product.get("product_id")
            name = (product.get("display_name") or product.get("product_name") or "").strip()
            if product_id is None or not name:
                continue
            wanted[product_id] = {
                "name": name,
                "category": category,
                # Which kind of resource is this product's own firmware line.
                "resource_type": "firmware" if product_type in self.HARDWARE_TYPES else "soft",
                "url": self._product_url(product),
            }

        devices: Dict[str, dict] = {}
        for record in resources:
            product = wanted.get(record.get("product_id"))
            if not product or record.get("type") != product["resource_type"]:
                continue
            if not record.get("version"):
                continue

            # Keyed by name so the two AudioFuse entries become one device holding
            # both halves of the history.
            device = devices.setdefault(
                product["name"],
                {"category": product["category"], "url": product["url"], "records": []},
            )
            device["records"].append(record)

        self._devices = devices
        return self._devices

    def _product_url(self, product: dict) -> str:
        """The product's own resources page, built from fields the API returns.

        Assembled rather than transcribed: both parts come from the catalogue, so a
        slug or a section Arturia renames cannot leave a stale URL behind.
        """
        category = product.get("category_alias") or "hardware-synths"
        slug = product.get("slug") or ""
        return f"{self.manufacturer_website}/products/{category}/{slug}/resources"

    async def fetch_device_list(self) -> ScraperResult:
        devices = await self._load()
        if devices is None:
            return ScraperResult(
                success=False, error="Could not read Arturia's product or resource API"
            )
        if not devices:
            return ScraperResult(
                success=False, error="Arturia's APIs returned no products with resources"
            )

        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category=device["category"],
                    firmware_page_url=device["url"],
                    product_url=device["url"],
                )
                for name, device in sorted(devices.items())
            ],
        )

    def _collect(self, records: List[dict]) -> List[ScrapedFirmware]:
        """One entry per version, keeping the earliest date it was published under."""
        best: Dict[str, dict] = {}
        for record in records:
            version = record["version"]
            date = self._parse_date(record.get("release_date"))
            current = best.get(version)
            if current is None or (
                date and current["date"] and date < current["date"]
            ):
                best[version] = {"date": date, "url": record.get("permalink")}

        return sorted(
            (
                ScrapedFirmware(
                    version=version,
                    release_date=entry["date"],
                    download_url=entry["url"],
                )
                for version, entry in best.items()
            ),
            key=lambda fw: self._version_key(fw.version),
            reverse=True,
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        devices = await self._load()
        if devices is None:
            return ScraperResult(
                success=False, error="Could not read Arturia's product or resource API"
            )

        device = devices.get(device_name)
        if device is None:
            # The device list is built from the same two endpoints, so a name that is
            # not in them is a product Arturia has withdrawn rather than a parse that
            # went wrong. Reporting it as a failure would be a permanent false alarm.
            return ScraperResult(success=True, firmware_versions=[])

        return ScraperResult(success=True, firmware_versions=self._collect(device["records"]))
