import json
import re
from typing import Dict, List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class TCElectronicScraper(BaseScraper):
    """TC Electronic hardware, read from the downloads on each product page.

    Product data is embedded in each page's Next.js RSC payload -- a `downloads`
    array typed Firmware / Driver / Manual / Software, with a version field -- and a
    plain fetch returns it; nothing needs rendering.

    **The products are the ones whose page offers versioned firmware.** The catalogue
    comes from /en/products, twelve to a page, each page's payload carrying
    `"products":[{"id":"0709-aiu","name":"DITTO+ LOOPER"}]` -- 107 products on
    2026-09-15, of which 20 publish a firmware version: the Ditto, Flashback,
    Plethora and HyperGravity pedals, the AMPWORX preamps, the TC1210/2290/8210-DT
    desktop controllers and the Clarity M meters. Every product page is read while
    listing, so the listing costs about two minutes and fetching versions afterwards
    costs nothing.

    Until then the products were a hand-kept list of nine handles, five of which
    publish no firmware at all (Ditto X4, Hall of Fame 2, Plethora X5 and both
    PolyTune 3 variants) while sixteen that do were missing. Those five keep their
    rows and report no firmware.

    The catalogue writes names in capitals. Rows already catalogued keep theirs,
    matched by handle; new products are title-cased word by word, leaving alone any
    word with a digit or symbol in it ("TC2290-DT", "X1", "65'").
    """

    manufacturer_name = "TC Electronic"
    manufacturer_slug = "tcelectronic"
    manufacturer_website = "https://www.tcelectronic.com"

    CATALOGUE_URL = "https://www.tcelectronic.com/en/products?page={page}"
    PRODUCT_URL = "https://www.tcelectronic.com/en/products/{handle}"

    # A pager that never ran dry would otherwise walk forever. 107 products at twelve
    # a page is nine pages.
    MAX_CATALOGUE_PAGES = 30

    # Handle -> the name its row was catalogued under.
    RENAMES = {
        "0709-afb": "Ditto Looper",
        "0709-aga": "Ditto X4",
        "0709-aiu": "Ditto+",
        "0709-agb": "Flashback 2",
        "0709-afs": "Hall of Fame 2",
        "0709-ais": "Plethora X3",
        "0709-aik": "Plethora X5",
        # Not catalogued before, but named like the two PolyTune 3 variants that were.
        "0713-aaj": "PolyTune 3",
        "0713-aam": "PolyTune 3 Mini",
        "0713-aan": "PolyTune 3 Noir",
    }

    # The handle's first part is the product line: 0709 pedals, 0713 tuners, 0815 the
    # desktop controllers for TC's plug-ins. Clarity (0842) and the rest are "other".
    CATEGORIES = {"0709": "guitar_pedal", "0713": "guitar_pedal", "0815": "midi_controller"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._catalogue: Optional[Dict[str, dict]] = None

    def _display_name(self, handle: str, name: str) -> str:
        if handle in self.RENAMES:
            return self.RENAMES[handle]
        return " ".join(word.capitalize() if word.isalpha() else word for word in name.split())

    def _catalogue_page(self, html: str) -> Optional[List[dict]]:
        """The products one catalogue page lists, or None when it carries no list."""
        payload = self._rsc_payload(html)
        marker = payload.find('"products":[')
        if marker < 0:
            return None
        span = self._match_bracket(payload, payload.index("[", marker))
        try:
            items = json.loads(span) if span else None
        except json.JSONDecodeError:
            return None
        if not isinstance(items, list):
            return None
        return [item for item in items if isinstance(item, dict) and item.get("id")]

    async def _load(self) -> Optional[Dict[str, dict]]:
        """Every product with versioned firmware, read once per scrape."""
        if self._catalogue is not None:
            return self._catalogue

        products: Dict[str, str] = {}
        for page in range(1, self.MAX_CATALOGUE_PAGES + 1):
            html = await self.fetch_page(self.CATALOGUE_URL.format(page=page))
            items = self._catalogue_page(html) if html else None
            if items is None:
                return None
            new = [item for item in items if item["id"] not in products]
            if not new:
                # Past the last page the list comes back empty.
                break
            for item in new:
                products[item["id"]] = item.get("name") or item["id"]

        if not products:
            return None

        catalogue: Dict[str, dict] = {}
        for handle, name in products.items():
            url = self.PRODUCT_URL.format(handle=handle)
            html = await self.fetch_page(url)
            downloads = self._extract_rsc_downloads(html) if html else None
            if downloads is None:
                # A page without its payload would silently drop a product.
                return None
            firmware = self._firmware_from_downloads(downloads)
            if firmware:
                catalogue[self._display_name(handle, name)] = {
                    "url": url, "handle": handle, "firmware": firmware,
                }

        self._catalogue = catalogue
        return catalogue

    # Next.js streams its RSC payload as a series of self.__next_f.push([1,"..."])
    # calls. A single JSON value can straddle two pushes, so the chunks must be
    # decoded and joined before parsing -- scanning the raw document instead finds
    # arrays truncated at a chunk boundary.
    _RSC_PUSH = re.compile(r'self\.__next_f\.push\(\[1,\s*"((?:[^"\\]|\\.)*)"\]\)', re.DOTALL)

    def _rsc_payload(self, html: str) -> str:
        """Decode and concatenate the page's RSC chunks into one string."""
        chunks = self._RSC_PUSH.findall(html)
        if chunks:
            try:
                return "".join(json.loads('"' + chunk + '"') for chunk in chunks)
            except json.JSONDecodeError:
                pass
        # Not an RSC page (or the chunks would not decode): fall back to a plain
        # unescape so a differently-built page still has a chance of parsing.
        return html.replace('\\"', '"')

    def _extract_rsc_downloads(self, html: str) -> Optional[List[dict]]:
        """Pull the downloads array out of the page's embedded Next.js RSC payload.

        The site streams its data as escaped JSON inside <script> pushes, so the
        quotes are backslashed and a plain JSON scan will not match. The marker can
        also appear more than once, and an occurrence may fall on a chunk boundary
        and be incomplete, so every occurrence is tried until one parses.

        Returns None when no occurrence yields a valid array -- meaning the page did
        not render its payload. That is distinct from an empty list, which means the
        product genuinely has no downloads.
        """
        if not html:
            return None

        unescaped = self._rsc_payload(html)
        marker = '"downloads":'
        pos = unescaped.find(marker)
        while pos >= 0:
            bracket = unescaped.find("[", pos)
            if bracket < 0:
                break
            span = self._match_bracket(unescaped, bracket)
            if span:
                try:
                    parsed = json.loads(span)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, list):
                    return parsed
            pos = unescaped.find(marker, pos + 1)

        return None

    @staticmethod
    def _match_bracket(text: str, start: int) -> Optional[str]:
        """Return the bracketed span beginning at start, ignoring brackets in strings."""
        depth = 0
        in_string = False
        escaped = False
        for pos in range(start, len(text)):
            char = text[pos]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    return text[start:pos + 1]
        return None

    @staticmethod
    def _clean_version(raw: Optional[str]) -> Optional[str]:
        """Strip a leading "Version"/"v" label -- some entries carry it, some do not."""
        if not raw:
            return None
        return re.sub(r"^\s*(?:version|ver\.?|v)\s*", "", str(raw), flags=re.I).strip() or None

    def _firmware_from_downloads(self, downloads: List[dict]) -> List[ScrapedFirmware]:
        """Keep the firmware entries that carry a version.

        Entries are typed Firmware / Driver / Manual. Release notes are typed
        Firmware but have no version, so requiring a version filters them out.
        """
        firmware = []
        seen = set()
        for item in downloads:
            if not isinstance(item, dict):
                continue
            if (item.get("downloadType") or "").lower() != "firmware":
                continue
            version = self._clean_version(item.get("version"))
            # Clarity M Stereo's "Firmware Release Note" is typed Firmware with version
            # "2", beside the 2.0.3 and 2.1.3 it describes. Every real release is dotted.
            if not version or "." not in version or version in seen:
                continue
            seen.add(version)
            firmware.append(
                ScrapedFirmware(
                    version=version,
                    # No date, deliberately. The download entries carry none, and the
                    # only dates in the payload belong to a used-gear listings widget
                    # on the same page -- listedDate, originalPurchaseDate, updatedAt.
                    # Those describe somebody's second-hand pedal, not a release, and
                    # attaching one to a firmware version would be an invention that
                    # looked like data. Checked 2026-09-12.
                    release_date=None,
                    download_url=item.get("fileUrl"),
                    changelog=item.get("title"),
                )
            )
        return firmware

    async def fetch_device_list(self) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(
                success=False,
                error=f"Could not read TC Electronic's catalogue and product pages from {self.CATALOGUE_URL.format(page=1)}",
            )

        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category=self.CATEGORIES.get(entry["handle"].split("-")[0], "other"),
                    firmware_page_url=entry["url"],
                    product_url=entry["url"],
                )
                for name, entry in catalogue.items()
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(
                success=False,
                error=f"Could not read TC Electronic's catalogue and product pages from {self.CATALOGUE_URL.format(page=1)}",
            )

        entry = catalogue.get(device_name)
        # Ditto X4, Hall of Fame 2, Plethora X5 and the PolyTune 3 variants publish no
        # firmware; their rows predate the catalogue and stay.
        return ScraperResult(success=True, firmware_versions=entry["firmware"] if entry else [])
