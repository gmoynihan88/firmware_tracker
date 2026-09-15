import json
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class ToontrackScraper(BaseScraper):
    """Toontrack -- EZdrummer, Superior Drummer, EZkeys, EZbass and EZmix, from its release notes.

    `/release-notes/` links one page per product generation, nine of them. Each lists
    every release as a server-rendered entry with its date and notes:

        <div class="list-group-item" title="Release notes for EZdrummer 3.1.2">
          <div class="collapse"><p class="small-bread">2025-11-11</p><p>EZdrummer 3.1.2 is now available...</p>

    `/wp-json/toontrack/v1/product-versions`, the endpoint the Product Manager app reads,
    gives each product's current version per platform with no date. It is a cross-check:
    a version it reports ahead of the notes is added, undated.

    **The page names the product; the entries do not.** Every EZdrummer 3 entry says
    "Release notes for EZdrummer 3.1.2" and every EZdrummer 2 entry "EZdrummer 2.2.3";
    the page heading says "EZdrummer 3". Devices are named by the heading, and the
    endpoint's "Superior Drummer 2.0" is the page's "Superior Drummer 2".

    **Not every entry is the product.** The EZbass page also carries Audio Sender, a
    separate plug-in; EZmix 3 has "EZmix 3 Core Pack update 3.1.0" and Superior Drummer
    3 "Superior Drummer 3 sound library update 1.1.1" -- content, not the application.
    Only entries naming the product itself are read.

    **Old entries carry the date they were imported.** Nine Superior Drummer 2 releases
    say 2018-03-19; EZdrummer 2.1.1, 2.1.0 and 2.0.1 say 2018-03-16; seven EZmix 2.0.x
    releases say 2018-10-22. One day stamped on three or more releases of a product is
    a bulk import into this site, and those dates are dropped.

    **What remains can still contradict the version order.** Superior Drummer 2.4.3 is
    dated 2015-04-30, before 2.4.0 (October 2015) and 2.4.2 (November 2015). A release
    cannot ship before an older one, so the largest set of dates that rises with the
    version is kept and the rest -- here 2.4.3 alone -- are dropped. Walking down from
    the newest and dropping anything later would have cost 2.4.2 and 2.4.0 instead,
    two real dates for one bad one.
    """

    manufacturer_name = "Toontrack"
    manufacturer_slug = "toontrack"
    manufacturer_website = "https://www.toontrack.com"

    BASE_URL = "https://www.toontrack.com"
    LISTING_URL = BASE_URL + "/release-notes/"
    VERSIONS_API = BASE_URL + "/wp-json/toontrack/v1/product-versions"
    PAGE = re.compile(r"^(?:https?://(?:www\.)?toontrack\.com)?/release-notes/[^/#?]+/?$")
    TITLE = re.compile(r"^Release\s+notes\s+for\s+(?P<name>.+?)\s+v?(?P<version>\d+(?:\.\d+)+)$", re.I)
    NOTES_LIMIT = 4000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._devices: Optional[Dict[str, Tuple[str, List[ScrapedFirmware]]]] = None

    # --- parsing ------------------------------------------------------------

    @staticmethod
    def _key(name: str) -> str:
        """"Superior Drummer 2.0" and "Superior Drummer 2" are one product."""
        return re.sub(r"\.0$", "", " ".join(name.lower().split()))

    @staticmethod
    def _numbers(version: str) -> Tuple[int, ...]:
        return tuple(int(n) for n in re.findall(r"\d+", version))

    def _parse_listing(self, html: str) -> List[str]:
        urls: List[str] = []
        for link in self.parse_html(html).find_all("a", href=True):
            href = link["href"].split("#")[0].split("?")[0]
            if self.PAGE.match(href):
                url = urljoin(self.BASE_URL, href.rstrip("/") + "/")
                if url != self.LISTING_URL and url not in urls:
                    urls.append(url)
        return urls

    def _parse_page(self, html: str) -> Optional[Tuple[str, List[ScrapedFirmware]]]:
        soup = self.parse_html(html)
        heading = soup.select_one("h4.mb-3") or soup.select_one("ol.breadcrumb li.active")
        name = " ".join(heading.get_text(" ").split()) if heading else ""
        if not name:
            return None
        own_names = {name.lower(), re.sub(r"\s+\d+(?:\.0)?$", "", name).lower()}

        versions: Dict[str, ScrapedFirmware] = {}
        for item in soup.select(".list-group-item"):
            anchor = item.select_one("a.release-notes-list")
            title = item.get("title") or (" ".join(anchor.get_text(" ").split()) if anchor else "")
            matched = self.TITLE.match(title)
            if not matched or matched.group("name").lower() not in own_names or matched.group("version") in versions:
                continue
            stamp = item.select_one("p.small-bread")
            try:
                released = datetime.strptime(" ".join(stamp.get_text(" ").split()), "%Y-%m-%d") if stamp else None
            except ValueError:
                released = None
            if stamp:
                stamp.extract()
            box = item.select_one(".collapse")
            lines = [line.strip() for line in (box.get_text("\n") if box else "").split("\n") if line.strip()]
            versions[matched.group("version")] = ScrapedFirmware(
                version=matched.group("version"), release_date=released,
                changelog="\n".join(lines)[: self.NOTES_LIMIT] or None,
            )
        if not versions:
            return None

        ordered = sorted(versions.values(), key=lambda fw: self._numbers(fw.version), reverse=True)
        self._drop_implausible_dates(ordered)
        return name, ordered

    @staticmethod
    def _drop_implausible_dates(versions: List[ScrapedFirmware]) -> None:
        """Clear import stamps, then the fewest dates that contradict the version order."""
        counts: Dict[datetime, int] = {}
        for firmware in versions:
            if firmware.release_date:
                counts[firmware.release_date] = counts.get(firmware.release_date, 0) + 1
        for firmware in versions:
            if firmware.release_date and counts[firmware.release_date] >= 3:
                firmware.release_date = None  # one day stamped on three releases is a bulk import

        dated = [fw for fw in reversed(versions) if fw.release_date]  # oldest version first
        # Longest run of dates that never goes backwards as versions go up; everything else is dropped.
        best = [1] * len(dated)
        previous = [-1] * len(dated)
        for i in range(len(dated)):
            for j in range(i):
                if dated[j].release_date <= dated[i].release_date and best[j] + 1 > best[i]:
                    best[i], previous[i] = best[j] + 1, j
        keep, i = set(), max(range(len(dated)), key=lambda k: best[k], default=-1)
        while i >= 0:
            keep.add(id(dated[i]))
            i = previous[i]
        for firmware in dated:
            if id(firmware) not in keep:
                firmware.release_date = None

    def _parse_api(self, body: str) -> Dict[str, str]:
        try:
            plugins = json.loads(body).get("plugins") or []
        except (ValueError, AttributeError):
            return {}
        current: Dict[str, str] = {}
        for plugin in plugins:
            name, version = (plugin.get("name") or "").strip(), (plugin.get("version") or "").strip()
            if not name or not re.match(r"^\d+(?:\.\d+)+$", version):
                continue
            key = self._key(name)
            if key not in current or self._numbers(version) > self._numbers(current[key]):
                current[key] = version  # the newest of the Mac and Windows builds
        return current

    # --- loading ------------------------------------------------------------

    async def _load(self) -> Optional[Dict[str, Tuple[str, List[ScrapedFirmware]]]]:
        if self._devices is not None:
            return self._devices
        listing = await self.fetch_page(self.LISTING_URL)
        pages = self._parse_listing(listing) if listing else []
        if not pages:
            return None
        api_body = await self.fetch_page(self.VERSIONS_API)
        current = self._parse_api(api_body) if api_body else {}

        devices: Dict[str, Tuple[str, List[ScrapedFirmware]]] = {}
        for url in pages:
            html = await self.fetch_page(url)
            parsed = self._parse_page(html) if html else None
            if parsed is None:
                logger.warning("Toontrack release notes page %s did not load or had no releases", url)
                continue
            name, versions = parsed
            reported = current.get(self._key(name))
            if reported and self._numbers(reported) > self._numbers(versions[0].version):
                versions.insert(0, ScrapedFirmware(
                    version=reported, release_date=None,
                    changelog="Current version reported by Toontrack's product-versions endpoint; no release notes yet."))
            devices.setdefault(name, (url, versions))
        self._devices = devices or None
        return self._devices

    async def fetch_device_list(self) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error=f"No Toontrack release notes found from {self.LISTING_URL}")
        return ScraperResult(
            success=True,
            devices=[ScrapedDevice(name=name, category="vst_plugin", firmware_page_url=url, product_url=url)
                     for name, (url, _versions) in devices.items()],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error=f"No Toontrack release notes found from {self.LISTING_URL}")
        _url, versions = devices.get(device_name, (None, []))
        return ScraperResult(success=True, firmware_versions=list(versions))
