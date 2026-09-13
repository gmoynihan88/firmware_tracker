import json
import logging
import re
from typing import Dict, Optional, Set

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class CableguysScraper(BaseScraper):
    """Cableguys -- ShaperBox, HalfTime, Kickstart, Curve and the older Shapers.

    The site is Nuxt, and the store's product records -- name, price, Paddle ids and
    the current `version` -- ship in the page's data payload, not its markup:

        /products/_payload.json?<build id>

    The build id changes on every deploy, so it is read from the page each run
    (`/_nuxt/builds/meta/<id>.json`). The payload is devalue-encoded: one flat JSON
    array in which every object's values are **indices** into that array. A product
    is `{"name": 412, "price": 413, "version": 414, "for_sale": 415, ...}`, and the
    strings around it are prices ("29.00") and ids that look just as version-shaped.
    Only the index an object names is read.

    Every page carries the same 26 records (checked on /products, /downloads,
    /shaperbox and /halftime, 2026-09-13), and they agree with the prose where the
    prose says anything: the ShaperBox page describes 3.6, the payload has 3.6.3.

    What is listed:
    - Current products and discontinued ones (`for_sale: false`) alike. VolumeShaper
      3 or ShaperBox 2 is still installed somewhere, and its last version is real.
      Each major is its own product, as Cableguys sells them.
    - **Not** the magazine and bundle editions -- "Curve CM", "Curve 2 BE",
      "VolumeShaper Sound Sonic Edition" -- which are variants of a listed product,
      one of them a release behind it.

    No dates: nothing on the site or in the payload carries one, and no changelog
    was found (no link from /products, /downloads or /shaperbox names one).
    """

    manufacturer_name = "Cableguys"
    manufacturer_slug = "cableguys"
    manufacturer_website = "https://www.cableguys.com"

    PRODUCTS_URL = "https://www.cableguys.com/products"

    BUILD_ID = re.compile(r"/_nuxt/builds/meta/([0-9a-f-]{36})\.json|_payload\.json\?([0-9a-f-]{36})")
    VERSION = re.compile(r"^\d+(?:\.\d+)+$")
    EDITION = re.compile(r"\s(?:CM|BE)$|\sEdition$")
    PAGE_PATH = re.compile(r"^/([a-z0-9-]+)/?$")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._products: Optional[Dict[str, str]] = None
        self._pages: Set[str] = set()

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(part) for part in version.split("."))

    def _payload_url(self, html: str) -> Optional[str]:
        matched = self.BUILD_ID.search(html)
        if not matched:
            return None
        return f"{self.PRODUCTS_URL}/_payload.json?{matched.group(1) or matched.group(2)}"

    def _parse_payload(self, payload: str) -> Dict[str, str]:
        try:
            data = json.loads(payload)
        except ValueError:
            return {}
        if not isinstance(data, list):
            return {}

        def at(index):
            return data[index] if isinstance(index, int) and 0 <= index < len(data) else None

        products: Dict[str, str] = {}
        for node in data:
            if not isinstance(node, dict) or "name" not in node or "version" not in node:
                continue
            name, version = at(node["name"]), at(node["version"])
            if not isinstance(name, str) or not isinstance(version, str):
                continue
            name, version = " ".join(name.split()), version.strip()
            if not self.VERSION.match(version) or self.EDITION.search(name):
                continue
            if name not in products or self._version_key(version) > self._version_key(products[name]):
                products[name] = version
        return products

    def _product_url(self, name: str) -> str:
        """"FilterShaper XL" -> /filtershaper-xl; "ShaperBox 3" -> /shaperbox; else /products."""
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        for candidate in (slug, re.sub(r"-\d+$", "", slug)):
            if candidate in self._pages:
                return f"{self.manufacturer_website}/{candidate}"
        return self.PRODUCTS_URL

    async def _load(self) -> Optional[Dict[str, str]]:
        if self._products is not None:
            return self._products

        html = await self.fetch_page(self.PRODUCTS_URL)
        payload_url = self._payload_url(html) if html else None
        if not payload_url:
            return None
        payload = await self.fetch_page(payload_url)
        products = self._parse_payload(payload) if payload else {}
        if not products:
            return None

        self._pages = {
            matched.group(1)
            for link in self.parse_html(html).find_all("a", href=True)
            if (matched := self.PAGE_PATH.match(link["href"]))
        }
        self._products = products
        return products

    async def fetch_device_list(self) -> ScraperResult:
        products = await self._load()
        if not products:
            return ScraperResult(success=False, error=f"No product versions in the payload behind {self.PRODUCTS_URL}")
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category="vst_plugin",
                    firmware_page_url=self.PRODUCTS_URL,
                    product_url=self._product_url(name),
                )
                for name in sorted(products)
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        products = await self._load()
        if not products:
            return ScraperResult(success=False, error=f"No product versions in the payload behind {self.PRODUCTS_URL}")
        if device_name not in products:
            return ScraperResult(success=True, firmware_versions=[])
        return ScraperResult(success=True, firmware_versions=[ScrapedFirmware(version=products[device_name])])
