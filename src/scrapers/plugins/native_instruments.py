import re
from typing import Dict, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class NativeInstrumentsScraper(BaseScraper):
    """Native Instruments software, read from NI's own "Official update status" threads.

    NI distributes through Native Access and publishes no version on its website.
    What it does publish is one closed forum thread per product whose title carries
    the current version: "Official update status - Kontakt (current version:
    8.13.0)". The numeric discussion id is stable even though the URL slug goes
    stale, and the discussions API returns the title as JSON, so no page is rendered.

    **The threads are found through the forum's sitemaps**, which robots.txt lists
    for crawlers: every discussion URL is in one, slug included, and the update
    threads' slugs begin "official-update-status". Nothing cheaper finds them all.
    Search is disallowed, the API's `closed` filter is ignored, and only one of the
    threads is pinned. Thirteen threads on 2026-09-15, across 72 sitemap files and
    about 85 seconds.

    Until 2026-09-15 the products were a hand-kept list of 40. Eight read threads by
    id; the rest carried static values, seven "superseded" and twenty-three
    "unverified", from a time before this route was known. Discovery added Traktor
    Pro 4, Ozone 12, Native Access and Maschine+, and moved Battery 4 from an
    unverified value to its thread. The static values are gone from the code; their
    rows keep what was stored and now report no published version.

    Titles name some products without the major version the catalogue names them
    by -- "Kontakt", "Reaktor" -- while "Guitar Rig 7" and "Absynth 6" carry it. For
    those two the major comes from the version, so a Kontakt 9 thread lists as
    "Kontakt 9" rather than moving the Kontakt 8 row onto 9.0.
    """

    manufacturer_name = "Native Instruments"
    manufacturer_slug = "nativeinstruments"
    manufacturer_website = "https://www.native-instruments.com"

    SITEMAP_INDEX = "https://community.native-instruments.com/sitemapindex.xml"
    DISCUSSION_API = "https://community.native-instruments.com/api/v2/discussions/{thread_id}"
    UPDATE_THREAD_URL = "https://community.native-instruments.com/discussion/{thread_id}"

    SITEMAP_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
    THREAD_LOC = re.compile(r"/discussion/(\d+)/official-update-status\b")

    TITLE_VERSION = re.compile(
        r"Official update status\s*-\s*(?P<product>.+?)\s*"
        r"\(current version:?\s*(?P<version>[^)]+)\)",
        re.I,
    )

    # Products whose thread title leaves out the major that names them in the catalogue.
    MAJOR_IN_NAME = {"Kontakt", "Reaktor"}

    # The title's name -> the catalogue's.
    RENAMES = {"Maschine +": "Maschine+"}

    # Everything else here is software. Maschine+ is the standalone groovebox.
    HARDWARE = {"Maschine+": "synthesizer"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._catalogue: Optional[Dict[str, dict]] = None

    def _product_name(self, title_product: str, version: str) -> str:
        name = re.sub(r"\s+", " ", title_product).strip()
        if name in self.MAJOR_IN_NAME:
            major = re.match(r"\d+", version)
            if major:
                name = f"{name} {major.group(0)}"
        return self.RENAMES.get(name, name)

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(p) for p in re.findall(r"\d+", version)) or (0,)

    async def _thread_ids(self) -> Optional[list]:
        index = await self.fetch_page(self.SITEMAP_INDEX)
        if not index:
            return None
        sitemaps = self.SITEMAP_LOC.findall(index)
        if not sitemaps:
            return None

        ids = []
        for sitemap in sitemaps:
            body = await self.fetch_page(sitemap)
            if body is None:
                # A missing sitemap would drop whatever threads it holds without a word.
                return None
            for thread_id in self.THREAD_LOC.findall(body):
                if thread_id not in ids:
                    ids.append(thread_id)
        return ids

    async def _load(self) -> Optional[Dict[str, dict]]:
        """Every update thread's product and current version, read once per scrape."""
        if self._catalogue is not None:
            return self._catalogue

        ids = await self._thread_ids()
        if not ids:
            return None

        catalogue: Dict[str, dict] = {}
        for thread_id in ids:
            discussion = await self.fetch_json(
                self.DISCUSSION_API.format(thread_id=thread_id),
                headers={"Accept": "application/json"},
            )
            title = (discussion or {}).get("name") or ""
            match = self.TITLE_VERSION.search(title)
            if not match:
                # Found by its slug but no longer titled as an update thread: the API
                # failed, or NI changed the format. Either way, not a reading to skip.
                return None

            version = match.group("version").strip()
            name = self._product_name(match.group("product"), version)
            existing = catalogue.get(name)
            if existing and self._version_key(existing["version"]) >= self._version_key(version):
                continue
            catalogue[name] = {
                "thread_id": thread_id,
                "version": version,
                "product": match.group("product").strip(),
            }

        self._catalogue = catalogue
        return catalogue

    async def fetch_device_list(self) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(
                success=False,
                error=f"Could not read NI's update threads via {self.SITEMAP_INDEX}",
            )

        devices = []
        for name, entry in catalogue.items():
            url = self.UPDATE_THREAD_URL.format(thread_id=entry["thread_id"])
            devices.append(
                ScrapedDevice(
                    name=name,
                    category=self.HARDWARE.get(name, "vst_plugin"),
                    firmware_page_url=url,
                    product_url=url,
                )
            )
        return ScraperResult(success=True, devices=devices)

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(
                success=False,
                error=f"Could not read NI's update threads via {self.SITEMAP_INDEX}",
            )

        entry = catalogue.get(device_name)
        if entry is None:
            # Kontakt 7, Raum and the rest of the old static list: NI keeps no update
            # thread for them, so there is no version to read.
            return ScraperResult(success=True, firmware_versions=[])

        url = self.UPDATE_THREAD_URL.format(thread_id=entry["thread_id"])
        return ScraperResult(
            success=True,
            firmware_versions=[
                ScrapedFirmware(
                    version=entry["version"],
                    download_url=url,
                    changelog=f"Reported by NI as current for {entry['product']}.",
                )
            ],
        )
