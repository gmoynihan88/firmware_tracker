import json
import logging
import re
from typing import Dict, List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class NovationScraper(BaseScraper):
    """Novation, read from the manifest its Components web app fetches.

    The downloads site is a dead end and looks like a thorough one. Every product
    page leads with "Novation USB Driver 2.30.0.83" -- the same version on all of
    them, because it is one driver -- followed by DAW integration scripts, and then
    a link reading "Go to Components Web". Peak and Summit list nothing but drivers.
    Launchkey MK4 has Software and Documentation sections and no firmware anywhere.
    Bass Station II is the closest to a trap: it offers "Librarian and Firmware
    Updater 1.2", which is the tool's version, while the instrument's own revision
    appears only inside release-notes prose as "upgraded firmware from r540 to r554".

    Reading any of that as the product's firmware gives a driver version, an editor
    version, or nothing. The conclusion looks obvious -- Novation is Focusrite, both
    Focusrite Group, firmware shipping inside an app with nothing published -- and it
    is wrong.

    `components.novationmusic.com` calls `/api/v2/firmwares` on load, and it answers
    without a key: 118 records over 24 products, with version, build and release
    notes.

        {"id": 181, "product": "flkey-mk2", "firmware_type": "firmware",
         "build": 1560, "version": "1.1.1560.0",
         "url": "https://components.novationmusic.com/api/v2/firmwares/181/file"}

    That is the whole catalogue in one request, and it carries products the downloads
    site does not admit have firmware at all: Peak and Summit are both on 2.2 here.

    **`firmware_type` has to be filtered, and not for tidiness.** Six of the records
    are `fpga`, and their versions collide exactly with the instrument firmware --
    Peak has an fpga 2.1 and a firmware 2.1, Summit likewise. Keeping both means one
    silently overwrites the other when versions are deduplicated, and the download
    recorded for "Peak 2.1" becomes the FPGA image. Only `firmware` is taken.

    **No release dates.** There is no date field in the manifest at all, so every
    version here is undated, the way Eventide's are. `created_at` is the only date
    these rows will carry, and the dashboard shows it as Discovered.

    One firmware covers a whole family: `launchkey-mk4` is the 25, 37, 49, 61 and 88,
    as Roland's System Program covers MC-101 and MC-707. The manifest is keyed by
    family, which is the right granularity, so the device list follows it rather than
    splitting into sizes the firmware does not distinguish.

    Names come from PRODUCTS below because the manifest has only slugs, and
    title-casing them produces "Bsii" and "Sl Mkiii" -- the same mangling that made
    the catalogue read "Ikmultimedia". A slug that is not in the map is still
    reported, under a tidied version of itself and with a warning, because a new
    Novation product appearing with an awkward name is visible and fixable, while one
    silently dropped is neither.
    """

    manufacturer_name = "Novation"
    manufacturer_slug = "novation"
    manufacturer_website = "https://novationmusic.com"

    FIRMWARE_API = "https://components.novationmusic.com/api/v2/firmwares"

    # Only the instrument's own firmware. See the class docstring: `fpga` versions
    # collide with these.
    FIRMWARE_TYPE = "firmware"

    # Manifest slug -> (display name, category). Novation's own spelling, taken from
    # the product ranges on downloads.novationmusic.com.
    PRODUCTS: Dict[str, tuple] = {
        "peak": ("Peak", "synthesizer"),
        "summit": ("Summit", "synthesizer"),
        "bsii": ("Bass Station II", "synthesizer"),
        "monostation": ("Circuit Mono Station", "synthesizer"),
        "circuit": ("Circuit", "synthesizer"),
        "circuit-tracks": ("Circuit Tracks", "synthesizer"),
        "circuit-rhythm": ("Circuit Rhythm", "synthesizer"),
        "launchpad-x": ("Launchpad X", "midi_controller"),
        "launchpad-mini-mk3": ("Launchpad Mini MK3", "midi_controller"),
        "launchpad-pro-mk3": ("Launchpad Pro MK3", "midi_controller"),
        "launchkey-mk3": ("Launchkey MK3", "midi_controller"),
        "launchkey-mini-mk3": ("Launchkey Mini MK3", "midi_controller"),
        "launchkey-mk4": ("Launchkey MK4", "midi_controller"),
        "launchkey-mini-mk4": ("Launchkey Mini MK4", "midi_controller"),
        "launchkey-88": ("Launchkey 88", "midi_controller"),
        "launch-control-mk1": ("Launch Control", "midi_controller"),
        "launch-control-mk3": ("Launch Control MK3", "midi_controller"),
        "launch-control-xl-mk2": ("Launch Control XL MK2", "midi_controller"),
        "launch-control-xl-mk3": ("Launch Control XL MK3", "midi_controller"),
        "sl-mkiii": ("SL MkIII", "midi_controller"),
        "flkey": ("FLkey", "midi_controller"),
        "flkey-mini": ("FLkey Mini", "midi_controller"),
        "flkey-mk2": ("FLkey MK2", "midi_controller"),
        "flkey-mini-mk2": ("FLkey Mini MK2", "midi_controller"),
    }

    # Where a person would go to read about an update, since the manifest itself is
    # a machine endpoint.
    COMPONENTS_URL = "https://components.novationmusic.com/"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._firmware: Optional[Dict[str, List[ScrapedFirmware]]] = None
        self._names: Dict[str, tuple] = {}

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(part) for part in re.findall(r"\d+", version or "")) or (0,)

    def _fallback_name(self, slug: str) -> str:
        """A readable name for a product added since PRODUCTS was written."""
        return " ".join(word.upper() if len(word) <= 2 else word.capitalize()
                        for word in slug.split("-"))

    async def _load(self) -> Optional[Dict[str, List[ScrapedFirmware]]]:
        if self._firmware is not None:
            return self._firmware

        raw = await self.fetch_page(self.FIRMWARE_API)
        if not raw:
            return None
        try:
            records = json.loads(raw).get("firmwares") or []
        except ValueError:
            return None
        if not records:
            return None

        grouped: Dict[str, List[ScrapedFirmware]] = {}
        for record in records:
            if record.get("firmware_type") != self.FIRMWARE_TYPE:
                continue
            slug = (record.get("product") or "").strip()
            version = (record.get("version") or "").strip()
            if not slug or not version:
                continue

            if slug in self.PRODUCTS:
                name, category = self.PRODUCTS[slug]
            else:
                name, category = self._fallback_name(slug), "midi_controller"
                logger.warning(
                    "Novation firmware for unmapped product %r; reporting it as %r",
                    slug, name,
                )
            self._names[name] = (slug, category)

            notes = (record.get("release_notes") or "").strip()
            grouped.setdefault(name, []).append(
                ScrapedFirmware(
                    version=version,
                    # The manifest carries no date field of any kind.
                    release_date=None,
                    download_url=record.get("url"),
                    changelog=notes[:500] or None,
                )
            )

        self._firmware = {
            name: sorted(versions, key=lambda fw: self._version_key(fw.version), reverse=True)
            for name, versions in grouped.items()
        }
        return self._firmware

    async def fetch_device_list(self) -> ScraperResult:
        firmware = await self._load()
        if firmware is None:
            return ScraperResult(
                success=False, error=f"Failed to read {self.FIRMWARE_API}"
            )

        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category=self._names[name][1],
                    firmware_page_url=self.COMPONENTS_URL,
                    product_url=self.COMPONENTS_URL,
                )
                for name in sorted(firmware)
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        firmware = await self._load()
        if firmware is None:
            return ScraperResult(
                success=False, error=f"Failed to read {self.FIRMWARE_API}"
            )

        versions = firmware.get(device_name)
        if versions is None:
            # Novation has dropped the product from the manifest. The endpoint
            # answered, so this is an absence rather than a break.
            return ScraperResult(success=True, firmware_versions=[])

        return ScraperResult(success=True, firmware_versions=versions)
