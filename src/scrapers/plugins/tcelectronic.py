import json
import re
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class TCElectronicScraper(BaseScraper):
    """Scraper for TC Electronic guitar pedals and effects."""

    manufacturer_name = "TC Electronic"
    manufacturer_slug = "tcelectronic"
    manufacturer_website = "https://www.tcelectronic.com"



    # Product handles verified against the store catalogue
    # (api-f2c-go-prod.empowertribe.com/store/products). The previous P0* codes and
    # the product.html?modelCode= path are both dead -- they return an empty shell.
    # Format: (name, category, product_page_url)
    PRODUCT_URL = "https://www.tcelectronic.com/en/products/{handle}"

    KNOWN_PRODUCTS = [
        ("Ditto+", "guitar_pedal", PRODUCT_URL.format(handle="0709-aiu")),
        ("Ditto X4", "guitar_pedal", PRODUCT_URL.format(handle="0709-aga")),
        ("Ditto Looper", "guitar_pedal", PRODUCT_URL.format(handle="0709-afb")),
        ("Flashback 2", "guitar_pedal", PRODUCT_URL.format(handle="0709-agb")),
        # TonePrint-only: the page lists manuals but no firmware. Kept so the empty
        # result is an explicit, verified fact rather than an unexplained gap.
        # See NO_FIRMWARE below.
        ("Hall of Fame 2", "guitar_pedal", PRODUCT_URL.format(handle="0709-afs")),
        ("Plethora X5", "guitar_pedal", PRODUCT_URL.format(handle="0709-aik")),
        ("Plethora X3", "guitar_pedal", PRODUCT_URL.format(handle="0709-ais")),
        # There is no base "PolyTune 3" in the catalogue, only these two variants.
        ("PolyTune 3 Mini", "guitar_pedal", PRODUCT_URL.format(handle="0713-aam")),
        ("PolyTune 3 Noir", "guitar_pedal", PRODUCT_URL.format(handle="0713-aan")),
    ]

    # Products established as taking no firmware at all, so their empty result reads
    # as the verified fact it is rather than as a scraper that stopped working.
    #
    # Only Hall of Fame 2 is on this list. Ditto X4, Plethora X5 and the PolyTune 3s
    # also report nothing and are probably the same story, but "probably" is not what
    # this field is for -- they stay unmarked until someone checks.
    NO_FIRMWARE = {
        "Hall of Fame 2": "no_firmware",
    }

    def _extract_model_code(self, url: str) -> Optional[str]:
        """Extract the product handle from a TC Electronic product URL.

        Handles the current /en/products/<handle> form as well as the legacy
        product.html?modelCode=<code> query form.
        """
        parsed = urlparse(url)
        model_codes = parse_qs(parsed.query).get("modelCode", [])
        if model_codes:
            return model_codes[0]
        parts = [seg for seg in parsed.path.split("/") if seg]
        if parts and parts[-1] != "products":
            return parts[-1]
        return None

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
            if not version or version in seen:
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
        """Return the list of known TC Electronic products."""
        devices = [
            ScrapedDevice(
                name=name,
                category=category,
                firmware_page_url=url,
                product_url=url,
                firmware_availability=self.NO_FIRMWARE.get(name),
            )
            for name, category, url in self.KNOWN_PRODUCTS
        ]
        return ScraperResult(success=True, devices=devices)

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        """Fetch firmware versions from a TC Electronic product page.

        The product data is embedded in the page's Next.js RSC payload rather than
        served by an API, so the page is rendered and the payload read out of it.
        """
        model_code = self._extract_model_code(firmware_page_url)

        html = await self.fetch_page_js(firmware_page_url, wait_for_timeout=20000)
        if not html:
            return ScraperResult(
                success=False,
                error=f"Failed to fetch {firmware_page_url}",
            )

        downloads = self._extract_rsc_downloads(html)
        if downloads is None:
            # No downloads array at all: the page did not render, or the handle is
            # stale. Either way this is a scrape failure, not an absence of firmware.
            return ScraperResult(
                success=False,
                error=(
                    f"No downloads data for {device_name} "
                    f"(handle={model_code or 'unknown'}): the product page did not "
                    "render its payload, which usually means the handle is stale"
                ),
            )

        # An empty result here is a real answer: some pedals ship no firmware at all
        # (Hall of Fame 2 is TonePrint-only), so this is success with nothing to sync.
        return ScraperResult(
            success=True,
            firmware_versions=self._firmware_from_downloads(downloads),
        )
