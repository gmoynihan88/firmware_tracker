import json
import logging
import re
from datetime import datetime
from typing import Dict, Iterator, List, Optional, Tuple
from urllib.parse import unquote

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class EngineDJScraper(BaseScraper):
    """Engine DJ -- Engine OS on Denon DJ, Numark and Rane hardware, and Engine DJ Desktop.

    inMusic's standalone DJ gear runs one operating system, Engine OS, and its library
    software is Engine DJ Desktop. `enginedj.com/downloads` is a Next.js page whose
    `__NEXT_DATA__` holds both histories from the CMS -- 39 OS releases back to 1.6.2
    (June 2021) and 15 Desktop releases, each with its date and rich-text notes:

        engineOsReleasesCollection.items[] =
          {"version": "v5.0.4", "releaseDate": "2026-07-28T00:00:00.000Z", "releaseNotes": {...},
           "hardwareUnitLinksCollection": {"items": [{"hardwareUnit": {"title": "SC LIVE 4"},
                                                      "usbUrl": ".../SCLIVE4-5.0.4-Update.img"}, ...]}}

    **A device is a hardware unit, and a release belongs only to the units it lists.**
    Engine OS 5.1.0 is "exclusive to Denon DJ PRIME 4 G2 users"; 4.5.0 and 4.6.0 went
    to the Rane SYSTEM ONE alone; 2.3.3 only to the SC LIVE 2 and 4. Giving every
    unit the newest release would put fifteen of sixteen a version ahead of anything
    they can install.

    **A unit listed with another release's files did not get that release.** Under
    5.0.4, the PRIME 4 G2 links the 5.1.0 updater -- it shipped with 5.1.0 and never
    ran 5.0.4. The files' own version decides. Today each URL names it twice, in a
    folder (`/Engine/5.1.0/`) and in the file name; the name is URL-encoded
    ("Prime%204%20G2%205.1.0%20Updater"), so URLs are decoded before reading -- otherwise
    a URL without the folder would read as 205.1.0 and the unit would lose its release.

    **The brand is only in the summary section.** The history lists each unit by title;
    the page's top section, which shows the current release, carries the brand, product
    type and product page. Devices are named "Denon DJ SC6000 PRIME", "Numark MIXSTREAM
    PRO", "Rane SYSTEM ONE", so they sort and search with the brand's other gear. The
    summary section's own release label lags (it said v5.0.4 while linking 5.1.0 files),
    so it supplies names and nothing else.

    DJ players are catalogued as other hardware, standalone controllers as MIDI
    controllers, Desktop with the other software.
    """

    manufacturer_name = "Engine DJ"
    manufacturer_slug = "enginedj"
    manufacturer_website = "https://enginedj.com"

    DOWNLOADS_URL = "https://enginedj.com/downloads"
    DESKTOP = "Engine DJ Desktop"
    CATEGORIES = {"standalone dj controller": "midi_controller", "dj player": "other"}
    NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
    FILE_VERSION = re.compile(r"(?<![\d.])(\d+\.\d+\.\d+)(?![\d.])")
    NOTES_LIMIT = 6000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._devices: Optional[Dict[str, Tuple[ScrapedDevice, List[ScrapedFirmware]]]] = None

    # --- parsing ------------------------------------------------------------

    @classmethod
    def _collections(cls, node, key: str) -> Iterator[list]:
        """Every `<key>.items` list anywhere in the page data."""
        if isinstance(node, dict):
            for name, value in node.items():
                if name == key and isinstance(value, dict) and isinstance(value.get("items"), list):
                    yield value["items"]
                else:
                    yield from cls._collections(value, key)
        elif isinstance(node, list):
            for value in node:
                yield from cls._collections(value, key)

    @classmethod
    def _history(cls, data, key: str) -> list:
        """The longest collection is the history; the others are the page's current-release summary."""
        return max(cls._collections(data, key), key=len, default=[])

    @classmethod
    def _notes(cls, node, out: List[str], bullet: bool = False) -> List[str]:
        """Flatten Contentful rich text into lines, bullets marked."""
        kind = node.get("nodeType")
        text = "".join(child.get("value", "") for child in node.get("content", []) if child.get("nodeType") == "text")
        if kind in ("paragraph", "heading-1", "heading-2", "heading-3") and text.strip():
            out.append(("- " if bullet else "") + " ".join(text.split()))
        for child in node.get("content", []):
            if child.get("nodeType") != "text":
                cls._notes(child, out, bullet or kind == "list-item")
        return out

    @staticmethod
    def _date(text: Optional[str]) -> Optional[datetime]:
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d") if text else None
        except ValueError:
            return None

    def _release(self, item: dict, download_url: Optional[str] = None) -> ScrapedFirmware:
        notes = self._notes((item.get("releaseNotes") or {}).get("json") or {}, [])
        return ScrapedFirmware(
            version=item["version"].strip().lstrip("vV"),
            release_date=self._date(item.get("releaseDate")),
            download_url=download_url,
            changelog="\n".join(notes)[: self.NOTES_LIMIT] or None,
        )

    def _parse_page(self, html: str) -> Dict[str, Tuple[ScrapedDevice, List[ScrapedFirmware]]]:
        found = self.NEXT_DATA.search(html or "")
        if not found:
            return {}
        try:
            data = json.loads(found.group(1))
        except ValueError:
            return {}

        # Brand, type and product page, from wherever the page gives them (the summary).
        units: Dict[str, dict] = {}
        for links in self._collections(data, "hardwareUnitLinksCollection"):
            for link in links:
                unit = link.get("hardwareUnit") or {}
                if unit.get("title") and unit.get("brand"):
                    units.setdefault(unit["title"], unit)

        devices: Dict[str, Tuple[ScrapedDevice, List[ScrapedFirmware]]] = {}
        for item in self._history(data, "engineOsReleasesCollection"):
            if not item.get("version"):
                continue
            version = item["version"].strip().lstrip("vV")
            for link in (item.get("hardwareUnitLinksCollection") or {}).get("items") or []:
                title = ((link.get("hardwareUnit") or {}).get("title") or "").strip()
                if not title:
                    continue
                files = unquote(" ".join(filter(None, (link.get("usbUrl"), link.get("macUrl"), link.get("winUrl")))))
                named = set(self.FILE_VERSION.findall(files))
                if named and version not in named:
                    continue  # the unit is listed with another release's updater
                unit = units.get(title, {})
                name = f"{unit['brand']} {title}" if unit.get("brand") else title
                if name not in devices:
                    category = self.CATEGORIES.get((unit.get("productType") or "").lower(), "other")
                    devices[name] = (ScrapedDevice(name=name, category=category, firmware_page_url=self.DOWNLOADS_URL,
                                                   product_url=unit.get("infoLink") or self.DOWNLOADS_URL), [])
                devices[name][1].append(self._release(item, link.get("usbUrl") or link.get("macUrl")))

        desktop = [self._release(item) for item in self._history(data, "engineDesktopReleasesCollection") if item.get("version")]
        if desktop:
            devices[self.DESKTOP] = (ScrapedDevice(name=self.DESKTOP, category="vst_plugin",
                                                   firmware_page_url=self.DOWNLOADS_URL, product_url=self.DOWNLOADS_URL), desktop)
        return devices

    # --- loading ------------------------------------------------------------

    async def _load(self) -> Optional[Dict[str, Tuple[ScrapedDevice, List[ScrapedFirmware]]]]:
        if self._devices is None:
            html = await self.fetch_page(self.DOWNLOADS_URL)
            devices = self._parse_page(html) if html else {}
            has_hardware = any(name != self.DESKTOP for name in devices)
            self._devices = devices if has_hardware else None
        return self._devices

    async def fetch_device_list(self) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error=f"No Engine OS releases in the page data at {self.DOWNLOADS_URL}")
        return ScraperResult(success=True, devices=[device for device, _versions in devices.values()])

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error=f"No Engine OS releases in the page data at {self.DOWNLOADS_URL}")
        _device, versions = devices.get(device_name, (None, []))
        return ScraperResult(success=True, firmware_versions=list(versions))
