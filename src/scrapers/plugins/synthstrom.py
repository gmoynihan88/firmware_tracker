import json
import logging
import re
from datetime import datetime
from typing import List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class SynthstromScraper(BaseScraper):
    """Synthstrom Audible -- Deluge firmware, from the releases of the community firmware repository.

    The Deluge's firmware is developed in the open at ``SynthstromAudible/DelugeFirmware``
    and published as GitHub releases, which the API serves without a token:

        GET https://api.github.com/repos/SynthstromAudible/DelugeFirmware/releases?per_page=100&page=1

    **Only stable releases are read.** A rolling "Deluge beta Release 20260914" is flagged
    ``prerelease`` and skipped, as are drafts.

    **The version comes from the release name, then the tag.** Names are regular --
    "Release 1.2.1 (Chopin)" -- but tags are written three ways: ``release_1_2_1``,
    ``v1.2.0`` and ``release_1_0`` for 1.0.0.

    **One publication date is out of order.** 1.0.0 was published on 2024-01-09, a day after
    1.0.1: the release was re-published, not first shipped then. Dates that disagree with
    version order are dropped by keeping the largest set falling down the list, so 1.0.0
    is stored undated rather than after its own successor.

    Ruled out, checked 2026-09-15: synthstrom.com's firmware page links no downloads or
    versions.
    """

    manufacturer_name = "Synthstrom Audible"
    manufacturer_slug = "synthstrom"
    manufacturer_website = "https://synthstrom.com"

    DEVICE_NAME = "Deluge"
    REPO = "SynthstromAudible/DelugeFirmware"
    RELEASES_API = "https://api.github.com/repos/" + REPO + "/releases?per_page={per_page}&page={page}"
    RELEASES_PAGE = "https://github.com/" + REPO + "/releases"
    PER_PAGE = 100
    MAX_PAGES = 10
    NAME_VERSION = re.compile(r"\bRelease\s+v?(?P<version>\d+(?:\.\d+)+)\b", re.I)
    TAG_VERSION = re.compile(r"^(?:v|release_)?(?P<version>\d+(?:[._]\d+)+)$", re.I)
    NOTES_LIMIT = 4000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._releases: Optional[List[ScrapedFirmware]] = None

    @classmethod
    def releases_url(cls, page: int) -> str:
        return cls.RELEASES_API.format(per_page=cls.PER_PAGE, page=page)

    # --- parsing ------------------------------------------------------------

    def _version(self, release: dict) -> Optional[str]:
        named = self.NAME_VERSION.search(release.get("name") or "")
        if named:
            return named.group("version")
        tagged = self.TAG_VERSION.match(release.get("tag_name") or "")
        return tagged.group("version").replace("_", ".") if tagged else None

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

    def _parse_releases(self, items: list) -> List[ScrapedFirmware]:
        releases: List[ScrapedFirmware] = []
        for release in items:
            if release.get("draft") or release.get("prerelease"):
                continue
            version = self._version(release)
            if not version:
                continue
            published = release.get("published_at")
            try:
                date = datetime.strptime(published[:10], "%Y-%m-%d") if published else None
            except ValueError:
                date = None
            notes = (release.get("body") or "").strip()
            releases.append(ScrapedFirmware(version=version, release_date=date,
                                            changelog=notes[: self.NOTES_LIMIT] or None))
        releases.sort(key=lambda r: tuple(int(p) for p in r.version.split(".")), reverse=True)
        self._keep_ordered_dates(releases)
        return releases

    # --- loading ------------------------------------------------------------

    async def _load(self) -> Optional[List[ScrapedFirmware]]:
        if self._releases is not None:
            return self._releases
        items: list = []
        for page in range(1, self.MAX_PAGES + 1):
            body = await self.fetch_page(self.releases_url(page))
            try:
                batch = json.loads(body) if body else None
            except ValueError:
                batch = None
            if not isinstance(batch, list):
                logger.warning("Deluge releases page %s did not load", page)
                return None
            items.extend(batch)
            if len(batch) < self.PER_PAGE:
                break
        self._releases = self._parse_releases(items) or None
        return self._releases

    async def fetch_device_list(self) -> ScraperResult:
        if not await self._load():
            return ScraperResult(success=False, error="Deluge firmware releases did not load")
        return ScraperResult(success=True, devices=[ScrapedDevice(
            name=self.DEVICE_NAME, category="synthesizer", firmware_page_url=self.RELEASES_PAGE,
            product_url=self.manufacturer_website,
        )])

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        releases = await self._load()
        if not releases:
            return ScraperResult(success=False, error="Deluge firmware releases did not load")
        return ScraperResult(success=True, firmware_versions=releases if device_name == self.DEVICE_NAME else [])
