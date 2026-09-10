import re
from datetime import datetime
from typing import Dict, List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class SteinbergScraper(BaseScraper):
    """Scraper for Steinberg products, read from their own forum announcements.

    Steinberg publishes nothing machine-readable. Downloads go through the Steinberg
    Download Assistant, a desktop app; /support/downloads/ is a stub that links to it
    and lists no versions; version-history PDFs live at URLs that embed the version
    you are trying to discover; and download.steinberg.net 403s anything but a known
    file path, including directory listings.

    What does exist is a maintenance announcement per release in each product's forum
    category, and the forum is Discourse, whose search API is public and returns JSON.
    That is a weaker source than a vendor's own version page and is treated as such:
    a version is only claimed for a product when the announcement title names that
    product, and titles must match a strict pattern to be read at all.
    """

    manufacturer_name = "Steinberg"
    manufacturer_slug = "steinberg"
    manufacturer_website = "https://www.steinberg.net"

    SEARCH_URL = "https://forums.steinberg.net/search.json?q={query}"
    SITE_URL = "https://forums.steinberg.net/site.json"

    # (device name, forum category, search term)
    #
    # HALion Sonic and Groove Agent SE ship on the same release train as the full
    # products, so they read the same announcements. The joint titles are the evidence:
    # "HALion 7.1.20 and HALion Sonic 7.1.20", "New Groove Agent (SE) 5.2.30" -- six
    # releases named both products and never once gave them different numbers. Later
    # titles abbreviate to "HALion 7.1.40 Maintenance available", but user threads in
    # the same forum reference HALion Sonic 7.1.40, so the train did not split; the
    # title just got shorter.
    PRODUCTS = [
        ("HALion", "HALion", "HALion maintenance"),
        ("HALion Sonic", "HALion", "HALion maintenance"),
        ("Groove Agent", "Groove Agent", "Groove Agent maintenance"),
        ("Groove Agent SE", "Groove Agent", "Groove Agent maintenance"),
        ("Cubase", "Cubase", "Cubase maintenance update"),
        ("Nuendo", "Nuendo", "Nuendo maintenance update"),
        ("WaveLab", "WaveLab", "WaveLab maintenance update"),
        ("Dorico", "Dorico", "Dorico maintenance update"),
    ]

    # "New Groove Agent (SE) 5.2.30 Maintenance available". Anchored at the start and
    # required to mention an update, which drops user threads that merely quote a
    # version -- "Error messages after installing HALion (Sonic) 7.1.30 maintenance".
    @staticmethod
    def _title_pattern(product: str) -> re.Pattern:
        return re.compile(
            rf"^(?:New\s+)?{re.escape(product)}\s*(?:\((?:SE|Sonic|HS)\))?\s*"
            rf"(\d+\.\d+(?:\.\d+)?)\b.*(?:maintenance|update)",
            re.I,
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._categories: Optional[Dict[int, str]] = None
        self._searches: Dict[str, list] = {}

    async def _get_json(self, url: str) -> Optional[dict]:
        await self._rate_limit()
        session = await self._get_session()
        try:
            async with session.get(url, headers={"Accept": "application/json"}) as response:
                if response.status != 200:
                    return None
                return await response.json(content_type=None)
        except Exception:
            return None

    async def _get_categories(self) -> Optional[Dict[int, str]]:
        if self._categories is not None:
            return self._categories
        site = await self._get_json(self.SITE_URL)
        if not site:
            return None
        self._categories = {c["id"]: c["name"] for c in site.get("categories", [])}
        return self._categories

    async def _search(self, query: str) -> Optional[list]:
        if query in self._searches:
            return self._searches[query]
        data = await self._get_json(self.SEARCH_URL.format(query=query.replace(" ", "%20")))
        if not data:
            return None
        self._searches[query] = data.get("topics") or []
        return self._searches[query]

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(p) for p in re.findall(r"\d+", version)) or (0,)

    async def fetch_device_list(self) -> ScraperResult:
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category="vst_plugin",
                    firmware_page_url=self.manufacturer_website,
                    product_url=self.manufacturer_website,
                )
                for name, _cat, _query in self.PRODUCTS
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        entry = next((p for p in self.PRODUCTS if p[0] == device_name), None)
        if not entry:
            return ScraperResult(
                success=False, error=f"No Steinberg product configured for {device_name}"
            )

        name, category, query = entry

        categories = await self._get_categories()
        topics = await self._search(query)
        if categories is None or topics is None:
            return ScraperResult(
                success=False, error="Could not read the Steinberg forum search API"
            )

        # Both members of a release train share a search term, so the second one
        # reads the cached results rather than searching again.
        pattern = self._title_pattern(category)

        releases = []
        seen = set()
        for topic in topics:
            title = topic.get("title") or ""

            if categories.get(topic.get("category_id")) != category:
                continue

            match = pattern.match(title)
            if not match:
                continue

            version = match.group(1)
            if version in seen:
                continue

            created = topic.get("created_at")
            release_date = None
            if isinstance(created, str):
                try:
                    release_date = datetime.strptime(created[:10], "%Y-%m-%d")
                except ValueError:
                    release_date = None

            seen.add(version)
            releases.append(
                ScrapedFirmware(
                    version=version,
                    release_date=release_date,
                    download_url=f"https://forums.steinberg.net/t/{topic.get('slug','')}/{topic.get('id','')}",
                    changelog=title,
                )
            )

        if not releases:
            return ScraperResult(
                success=False,
                error=f"No maintenance announcements found for {name} in the {category} forum",
            )

        return ScraperResult(
            success=True,
            firmware_versions=sorted(
                releases, key=lambda fw: self._version_key(fw.version), reverse=True
            ),
        )
