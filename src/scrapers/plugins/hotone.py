import json
import logging
import re
from collections import Counter
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class HotoneScraper(BaseScraper):
    """Hotone -- Ampero, Pulze, Verbera, Omni, Binary and the rest, from its support API.

    hotoneaudio.com's support page is a Nuxt app, and the firmware list it renders
    comes from one JSON call its own page makes:

        GET /api/index/support?language=1&support_type=2&show_lang=1
        {"data": [{"name": "Pulze Mini Firmware V1.1.2(Compatible with Pulze Editor V2.0.2)",
                   "product_id": "[103,107]", "created_at": "2026-07-21T...", "file": "{...}"}, ...]}

    104 rows on 2026-09-14, back to the Ampero's 2019 firmware, one row per download.

    **A device is the set of products a firmware row serves.** Rows list product ids,
    and ids that share a row are one device: Ampero and Ampero Silver Edition get the
    same firmware, and Pulze Mini's two ids (colour editions) always appear together.
    The Ampero Pink Limited Edition is separate -- its firmware is lettered (V5.2A,
    V3.3B) and only ever listed under its own ids. A device is named by the model its
    rows name most often: "Ampero Firmware V3.3B For Pink Limited Edition" names "Ampero
    Pink Limited Edition", not "Ampero".

    **The version is the firmware's, not the editor's.** "(Compatible with Pulze Editor
    V2.0.2)" follows most names; the version read is the one after "Firmware", written
    "Firmware V1.4.0", "FirmwareV1.4.0", "Firmware  V1.1.0" and "Firmware Update V1.1.0",
    with suffixes kept -- V1.0B, V5.2A, V1.2SP1.

    **Not every row is a release of the unit.** "Important Notice for Windows 11 Users"
    and "Solution of Ampero II Stomp ... Connection Problem" have no version; "Jogg
    Firmware with Hotone ASIO Driver support" has none either; "Ampero II Stomp USB
    Audio Firmware V2.01" is the USB audio chip's firmware, not the Stomp's.

    **The date is when Hotone posted the download, and early posts were uploaded in
    bulk.** Ampero 2.1, 3.0, 3.1 and 3.2 all say 2019-09-20, when the site's support
    section launched; Omni IR 1.2 and 1.3 share a day as well. A day on two or more
    releases of one device is dropped, and of the dates left, the largest set that rises
    with the version is kept -- Pulze 1.0.6, posted after 1.0.8, loses its date; where
    two choices keep as many dates, the newer release keeps its own. A model named as
    often as another yields to the more specific (longer) name.
    """

    manufacturer_name = "Hotone"
    manufacturer_slug = "hotone"
    manufacturer_website = "https://www.hotoneaudio.com"

    API_URL = "https://www.hotoneaudio.com/api/index/support?language=1&support_type=2&show_lang=1"
    PAGE_URL = "https://www.hotoneaudio.com/support/2"

    VERSION = re.compile(r"Firmware(?:\s+Update)?\s*V(?P<version>\d+(?:\.\d+)*[A-Z]?(?:SP\d+)?)(?![\w.])", re.I)
    FIRMWARE_WORD = re.compile(r"Firmware", re.I)
    FOR_EDITION = re.compile(r"\bFor\s+(?P<model>[\w ]+?Edition)\b", re.I)
    COMPONENT = re.compile(r"\bUSB\s+Audio\b", re.I)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._devices: Optional[Dict[str, List[ScrapedFirmware]]] = None

    # --- parsing ------------------------------------------------------------

    @staticmethod
    def _sort_key(version: str) -> Tuple:
        numbers = [int(n) for n in re.findall(r"\d+", re.sub(r"SP\d+$", "", version, flags=re.I))]
        service_pack = re.search(r"SP(\d+)$", version, re.I)
        letter = re.search(r"\d([A-Z])(?:SP\d+)?$", version, re.I)
        return (*numbers, letter.group(1).upper() if letter else "", int(service_pack.group(1)) if service_pack else 0)

    @staticmethod
    def _clean_dates(versions: List[ScrapedFirmware]) -> None:
        """Drop bulk-upload days, then the fewest dates that contradict the version order."""
        days = Counter(fw.release_date for fw in versions if fw.release_date)
        for firmware in versions:
            if firmware.release_date and days[firmware.release_date] >= 2:
                firmware.release_date = None

        # Newest version first, so that between two equally long runs the newer releases keep their dates.
        dated = [fw for fw in versions if fw.release_date]
        best, previous = [1] * len(dated), [-1] * len(dated)
        for i in range(len(dated)):
            for j in range(i):
                if dated[j].release_date >= dated[i].release_date and best[j] + 1 > best[i]:
                    best[i], previous[i] = best[j] + 1, j
        keep, i = set(), max(range(len(dated)), key=lambda k: best[k], default=-1)
        while i >= 0:
            keep.add(id(dated[i]))
            i = previous[i]
        for firmware in dated:
            if id(firmware) not in keep:
                firmware.release_date = None

    def _parse(self, body: str) -> Dict[str, List[ScrapedFirmware]]:
        try:
            rows = json.loads(body).get("data") or []
        except (ValueError, AttributeError):
            return {}

        parent: Dict[str, str] = {}

        def root(key: str) -> str:
            while parent.setdefault(key, key) != key:
                parent[key] = parent[parent[key]]
                key = parent[key]
            return key

        entries = []
        for row in rows:
            name = " ".join(str(row.get("name") or "").split())
            matched = self.VERSION.search(name)
            if not matched:
                continue  # a notice, or firmware posted with no version
            model = name[: self.FIRMWARE_WORD.search(name).start()].strip()
            if not model or self.COMPONENT.search(model):
                continue
            edition = self.FOR_EDITION.search(name[matched.end():])
            if edition:
                named = edition.group("model").strip()
                base = model.split()[0]
                model = named if named.lower().startswith(base.lower()) else f"{base} {named}"
            try:
                ids = [str(i) for i in json.loads(row.get("product_id") or "[]")]
            except ValueError:
                ids = []
            keys = [f"id:{i}" for i in ids] or [f"model:{model.lower()}"]
            for key in keys[1:]:
                parent[root(key)] = root(keys[0])
            try:
                released = datetime.strptime(str(row.get("created_at"))[:10], "%Y-%m-%d")
            except ValueError:
                released = None
            try:
                url = json.loads(row.get("file") or "{}").get("url")
            except ValueError:
                url = None
            entries.append((keys[0], model, matched.group("version"), released, url, name))

        grouped: Dict[str, List[tuple]] = {}
        for entry in entries:
            grouped.setdefault(root(entry[0]), []).append(entry)

        devices: Dict[str, List[ScrapedFirmware]] = {}
        for group in grouped.values():
            counts = Counter(entry[1] for entry in group)
            model = max((name for name, count in counts.items() if count == max(counts.values())), key=len)
            versions: Dict[str, ScrapedFirmware] = {}
            for _key, _model, version, released, url, name in group:
                known = versions.get(version)
                if known is None or (released and (known.release_date is None or released < known.release_date)):
                    versions[version] = ScrapedFirmware(version=version, release_date=released, download_url=url, changelog=name)
            ordered = sorted(versions.values(), key=lambda fw: self._sort_key(fw.version), reverse=True)
            self._clean_dates(ordered)
            devices[f"Hotone {model}"] = ordered
        return devices

    # --- loading ------------------------------------------------------------

    async def _load(self) -> Optional[Dict[str, List[ScrapedFirmware]]]:
        if self._devices is None:
            body = await self.fetch_page(self.API_URL)
            self._devices = (self._parse(body) if body else {}) or None
        return self._devices

    async def fetch_device_list(self) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error=f"No Hotone firmware found at {self.API_URL}")
        return ScraperResult(
            success=True,
            devices=[ScrapedDevice(name=name, category="guitar_pedal", firmware_page_url=self.PAGE_URL,
                                   product_url=self.PAGE_URL) for name in devices],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error=f"No Hotone firmware found at {self.API_URL}")
        return ScraperResult(success=True, firmware_versions=list(devices.get(device_name, [])))
