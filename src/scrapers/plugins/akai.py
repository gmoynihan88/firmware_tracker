import json
import re
from typing import Dict, List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class AkaiScraper(BaseScraper):
    """Akai Professional, read from the Gatsby page data behind its downloads page.

    `/downloads` renders nothing server-side and about 1,900 characters in a browser.
    The site is Gatsby, so the content arrives as page data, and the downloads listing
    is a static query whose result holds every product with its downloads attached:

        {"description": "Recommended: MPC 3.9 Firmware Update", "type": "Firmware Update",
         "version": "3.9", "url": ".../downloads/firmware/mpc/"}

    **The query hash is discovered, not hardcoded.** Gatsby names that file
    `sq/d/2008607954.json`, and the number is a build artefact that changes whenever
    the site is rebuilt. `page-data.json` for the downloads route lists it under
    `staticQueryHashes`, so both are fetched in order and a rebuild cannot leave a
    stale URL behind -- the failure that killed every Focusrite and GForce product URL.

    `type` separates the firmware from the 256 user manuals, 222 guided setups, 76
    editors and 53 drivers sharing the same array, which is the same discriminator
    Novation's manifest and Arturia's resources endpoint provide.

    **Versions are only half in the `version` field.** Where it is empty the number
    sits in the description, and taking it from there is where this vendor punishes
    carelessness:

        "Advance 25 - Firmware ReadMe (76.74 kB)"        -> 76.74 is a file size
        "MPC 2.11.10 Software Update (74.64 kB)"         -> the MPC software, not the
                                                            device's firmware
        "MPC Studio Windows Firmware Update v1.10"       -> 1.10, genuinely
        "MPC2500 Operating System [v1.24]"               -> 1.24, genuinely

    A first pass reading any version-shaped string out of the description gave Advance
    25 a firmware of 76.74 and MPC Element one of 2.11.10. So parenthesised sizes are
    stripped, and prose is only trusted where the number carries an explicit `v` --
    which the real versions do and the file sizes and software releases do not. That
    drops 37 products to 28 and is the right trade.

    The "Legacy MPC Firmware (Gen 1)" and "(Gen 2)" entries are excluded. They are not
    products but archives holding every historical MPC updater, and importing them
    would add two rows whose version is whichever updater sorted last.

    **No dates.** Nothing in the payload carries one, so these join Eventide's and
    Novation's as undated. `created_at` is the only date these rows will have.
    """

    manufacturer_name = "Akai Professional"
    manufacturer_slug = "akai"
    manufacturer_website = "https://www.akaipro.com"

    PAGE_DATA = "https://www.akaipro.com/page-data/downloads-and-support/downloads/page-data.json"
    STATIC_QUERY = "https://www.akaipro.com/page-data/sq/d/{}.json"

    DOWNLOADS_URL = "https://www.akaipro.com/downloads-and-support/downloads/"

    FIRMWARE_TYPE = "firmware"

    # Archives of historical updaters rather than products.
    NOT_A_PRODUCT = ("legacy mpc firmware",)

    # A clean version in the `version` field.
    VERSION_FIELD = re.compile(r"\d+(?:\.\d+)+")
    # In prose, only where an explicit v marks it. "Updater v1.0.10", "[v1.24]".
    VERSION_IN_PROSE = re.compile(r"[\[(]?v(\d+(?:\.\d+)+)", re.I)
    # "(76.74 kB)" and friends, removed before any prose is read.
    FILE_SIZE = re.compile(r"\(\s*[\d.]+\s*[kKmMgG]?B\s*\)")

    CATEGORY_MAP = {
        "Products > Controllers": "midi_controller",
        "Products > Instruments": "synthesizer",
    }
    DEFAULT_CATEGORY = "synthesizer"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._catalogue: Optional[Dict[str, dict]] = None

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(part) for part in re.findall(r"\d+", version)) or (0,)

    def _version_of(self, entry: dict) -> Optional[str]:
        raw = (entry.get("version") or "").strip()
        if self.VERSION_FIELD.fullmatch(raw):
            return raw
        description = self.FILE_SIZE.sub("", entry.get("description") or "")
        found = self.VERSION_IN_PROSE.search(description)
        return found.group(1) if found else None

    def _category_of(self, product: dict) -> str:
        for level in (product.get("categories") or {}).get("lvl1") or []:
            if level in self.CATEGORY_MAP:
                return self.CATEGORY_MAP[level]
        return self.DEFAULT_CATEGORY

    def _parse_catalogue(self, payload: dict) -> Dict[str, dict]:
        """Products that publish at least one firmware version."""
        models = (payload.get("data") or {}).get("allBuilderModels") or {}
        records = []
        for group in models.values():
            if isinstance(group, list):
                records.extend(group)

        catalogue: Dict[str, dict] = {}
        for record in records:
            product = record.get("data") or {}
            name = (product.get("name") or "").strip()
            if not name or name.lower().startswith(self.NOT_A_PRODUCT):
                continue

            versions: Dict[str, ScrapedFirmware] = {}
            for entry in product.get("downloads") or []:
                if self.FIRMWARE_TYPE not in (entry.get("type") or "").lower():
                    continue
                version = self._version_of(entry)
                if not version or version in versions:
                    continue
                versions[version] = ScrapedFirmware(
                    version=version,
                    # Nothing in the payload carries a release date.
                    release_date=None,
                    download_url=entry.get("url"),
                    changelog=(entry.get("description") or "").strip()[:500] or None,
                )

            if versions:
                catalogue[name] = {
                    "category": self._category_of(product),
                    "url": product.get("url") or "",
                    "versions": sorted(
                        versions.values(),
                        key=lambda fw: self._version_key(fw.version),
                        reverse=True,
                    ),
                }

        return catalogue

    async def _load(self) -> Optional[Dict[str, dict]]:
        if self._catalogue is not None:
            return self._catalogue

        raw = await self.fetch_page(self.PAGE_DATA)
        if not raw:
            return None
        try:
            hashes = json.loads(raw).get("staticQueryHashes") or []
        except ValueError:
            return None

        for query_hash in hashes:
            body = await self.fetch_page(self.STATIC_QUERY.format(query_hash))
            if not body:
                continue
            try:
                payload = json.loads(body)
            except ValueError:
                continue
            catalogue = self._parse_catalogue(payload)
            if catalogue:
                self._catalogue = catalogue
                return catalogue

        return None

    async def fetch_device_list(self) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(
                success=False,
                error="Could not read Akai's downloads page data",
            )

        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category=entry["category"],
                    firmware_page_url=self.DOWNLOADS_URL,
                    product_url=(
                        f"{self.manufacturer_website}{entry['url']}"
                        if entry["url"].startswith("/") else self.DOWNLOADS_URL
                    ),
                )
                for name, entry in sorted(catalogue.items())
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(
                success=False, error="Could not read Akai's downloads page data"
            )

        entry = catalogue.get(device_name)
        if entry is None:
            # Akai has dropped the product from the listing. The payload loaded, so
            # this is an absence rather than a break.
            return ScraperResult(success=True, firmware_versions=[])

        return ScraperResult(success=True, firmware_versions=entry["versions"])
