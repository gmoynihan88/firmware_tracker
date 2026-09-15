import json
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class OXIScraper(BaseScraper):
    """OXI Instruments -- OXI One MKII, OXI One, E16, Coral and Meta firmware, from their release feeds.

    oxiinstruments.com/support prints a "Latest Firmware" version per product, but the
    printed values are a stale fallback: the page's own ``firmware-app-script`` replaces
    them in the browser with the latest release from each product's feed --

        GitHub  OXI-Instruments/OXI-One-MkII-Releases, OXI-Instruments/OXI-E16-Releases,
                oxiinstruments/coral-releases, oxiinstruments/meta-releases
        GitLab  project 25470905 (the original OXI One, "manuwind5/oxi-beta")

    -- which is why the static page says OXI One MKII 0.15.5 while its feed is on 2.2.2.
    This reads the whole of each feed, not only the latest release.

    **The release name is the version, not the tag.** OXI's script shows ``name``, and the
    tags lag it: tag 0.16.6 is release 0.16.7, GitLab tag 6.0 is 6.0.2, tag 4.0.11 is 4.1.0.
    Only a release with no name falls back to its tag -- the OXI One project is literally
    "oxi-beta", and 58 of its 146 releases are named "3.5.9 BETA", "v2.9b20", "v1.0.2-pre
    fixed memory issues." or "EUCLIDEAN, 32 MIDI Ch, ANALOG Clock" over tags that look like
    versions. A name counts when it is a version, optionally followed by prose that does
    not say beta, pre or rc ("v1.0.3 new release with several bugfixes" is 1.0.3); letter
    suffixes such as "v1.0.9c" and "v2.9b20" are builds, not releases.

    **Betas are published as ordinary releases.** The OXI One MKII's firmware up to 0.15.0
    and its first 2.0.0 ship as ``OXI_ONE_MKII_0_14_5.BETA.syx``; neither GitHub's
    ``prerelease`` flag nor the name says so, only the file. Releases whose firmware file
    is marked BETA are skipped.

    **A name can be published twice.** GitLab has two "4.2.4" releases, tagged 4.2.4 and
    4.2.0; the newer is kept. Dates that disagree with version order are dropped by
    keeping the largest set falling down the list.

    Feeds are paged until a short page. A feed that fails loads nothing for that product
    rather than a history cut short; the product is reported without firmware, and the
    scrape fails only if every feed does.
    """

    manufacturer_name = "OXI Instruments"
    manufacturer_slug = "oxi"
    manufacturer_website = "https://oxiinstruments.com"

    SUPPORT_URL = "https://oxiinstruments.com/support"
    GITHUB = "https://api.github.com/repos/{repo}/releases?per_page={per_page}&page={page}"
    GITLAB = "https://gitlab.com/api/v4/projects/{project}/releases?per_page={per_page}&page={page}"
    PRODUCTS: Dict[str, Tuple[str, str, str]] = {
        "OXI One MKII": ("github", "OXI-Instruments/OXI-One-MkII-Releases", "midi_controller"),
        "OXI One": ("gitlab", "25470905", "midi_controller"),
        "OXI E16": ("github", "OXI-Instruments/OXI-E16-Releases", "midi_controller"),
        "OXI Coral": ("github", "oxiinstruments/coral-releases", "synthesizer"),
        "OXI Meta": ("github", "oxiinstruments/meta-releases", "other"),
    }
    PER_PAGE = 100
    MAX_PAGES = 10
    VERSION = re.compile(r"^v?(?P<version>\d+(?:\.\d+)*)(?:\s+(?P<rest>.*))?$")
    PRERELEASE = re.compile(r"(?i)\b(?:beta|pre|rc|alpha)\b|-pre\b")
    BETA_FILE = re.compile(r"\.BETA\.", re.I)
    NOTES_LIMIT = 4000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._devices: Optional[Dict[str, List[ScrapedFirmware]]] = None

    @classmethod
    def feed_url(cls, kind: str, source: str, page: int) -> str:
        template = cls.GITHUB if kind == "github" else cls.GITLAB
        return template.format(repo=source, project=source, per_page=cls.PER_PAGE, page=page)

    # --- parsing ------------------------------------------------------------

    def _version(self, release: dict) -> Optional[str]:
        label = (release.get("name") or "").strip() or (release.get("tag_name") or "").strip()
        matched = self.VERSION.match(label)
        if not matched or self.PRERELEASE.search(matched.group("rest") or ""):
            return None
        return matched.group("version")

    @staticmethod
    def _files(release: dict) -> List[str]:
        """A GitHub release's firmware file names; GitLab links are named by version only."""
        assets = release.get("assets")
        return [asset.get("name") or "" for asset in assets if isinstance(asset, dict)] if isinstance(assets, list) else []

    @staticmethod
    def _keep_ordered_dates(releases: List[ScrapedFirmware]) -> None:
        """Drop dates that disagree with version order, keeping the largest set falling down the list."""
        dated = [i for i, release in enumerate(releases) if release.release_date]
        best: List[List[int]] = []
        for position, index in enumerate(dated):
            chain = [index]
            for earlier in range(position):
                candidate = best[earlier]
                if releases[candidate[-1]].release_date >= releases[index].release_date and len(candidate) + 1 > len(chain):
                    chain = candidate + [index]
            best.append(chain)
        keep = set(max(best, key=len)) if best else set()
        for index in dated:
            if index not in keep:
                releases[index].release_date = None

    def _parse_feed(self, items: list) -> List[ScrapedFirmware]:
        releases: List[ScrapedFirmware] = []
        for release in items:
            if release.get("draft") or release.get("prerelease"):
                continue
            if any(self.BETA_FILE.search(name) for name in self._files(release)):
                continue
            version = self._version(release)
            if not version or version in {r.version for r in releases}:
                continue
            stamp = release.get("published_at") or release.get("released_at") or ""
            try:
                date = datetime.strptime(stamp[:10], "%Y-%m-%d") if stamp else None
            except ValueError:
                date = None
            notes = (release.get("body") or release.get("description") or "").strip()
            releases.append(ScrapedFirmware(version=version, release_date=date, changelog=notes[: self.NOTES_LIMIT] or None))
        releases.sort(key=lambda r: tuple(int(p) for p in r.version.split(".")), reverse=True)
        self._keep_ordered_dates(releases)
        return releases

    # --- loading ------------------------------------------------------------

    async def _feed(self, kind: str, source: str) -> Optional[list]:
        items: list = []
        for page in range(1, self.MAX_PAGES + 1):
            body = await self.fetch_page(self.feed_url(kind, source, page))
            try:
                batch = json.loads(body) if body else None
            except ValueError:
                batch = None
            if not isinstance(batch, list):
                return None
            items.extend(batch)
            if len(batch) < self.PER_PAGE:
                break
        return items

    async def _load(self) -> Optional[Dict[str, List[ScrapedFirmware]]]:
        if self._devices is not None:
            return self._devices
        devices: Dict[str, List[ScrapedFirmware]] = {}
        loaded = 0
        for name, (kind, source, _category) in self.PRODUCTS.items():
            items = await self._feed(kind, source)
            if items is None:
                logger.warning("OXI release feed for %s (%s %s) did not load", name, kind, source)
                devices[name] = []
                continue
            loaded += 1
            devices[name] = self._parse_feed(items)
        self._devices = devices if loaded else None
        return self._devices

    async def fetch_device_list(self) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error="No OXI release feed could be read")
        return ScraperResult(
            success=True,
            devices=[ScrapedDevice(name=name, category=self.PRODUCTS[name][2], firmware_page_url=self.SUPPORT_URL,
                                   product_url=self.SUPPORT_URL) for name in devices],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error="No OXI release feed could be read")
        return ScraperResult(success=True, firmware_versions=devices.get(device_name, []))
