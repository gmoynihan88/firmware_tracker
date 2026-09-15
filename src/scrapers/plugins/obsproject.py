import json
import logging
import re
from datetime import datetime
from typing import List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class OBSProjectScraper(BaseScraper):
    """OBS Studio, from the releases of its GitHub repository.

    OBS publishes every build as a GitHub release of `obsproject/obs-studio`, and the
    API answers without a token: 247 releases on 2026-09-15, back to 0.4.0 in July
    2014, each with its publication date and its notes.

        GET https://api.github.com/repos/obsproject/obs-studio/releases?per_page=100&page=1

    **Only stable releases are read.** 90 of the 247 are release candidates and betas
    ("32.2.0-rc1", "32.1.0-beta2"). GitHub flags them `prerelease`, and the tag must
    also be a plain version, so one mislabelled release cannot pass for a stable build.
    Drafts are skipped too.

    **Pages are followed until a short one**, three requests today. A page that fails
    to load fails the scrape: the likeliest cause is the unauthenticated API's 60
    requests an hour, and a history cut short at page two would otherwise pass for
    complete.

    obsproject.com's download page states the same current version ("Version: 32.2.2
    Released: August 14th") without a year, so the API is the better source.

    One device, "OBS Studio", catalogued with the other desktop software.
    """

    manufacturer_name = "OBS Project"
    manufacturer_slug = "obsproject"
    manufacturer_website = "https://obsproject.com"

    RELEASES_API = "https://api.github.com/repos/obsproject/obs-studio/releases?per_page={per_page}&page={page}"
    PRODUCT_URL = "https://obsproject.com/download"
    PRODUCT_NAME = "OBS Studio"
    PER_PAGE = 100
    MAX_PAGES = 10

    STABLE_TAG = re.compile(r"^\d+\.\d+(?:\.\d+)?$")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._versions: Optional[List[ScrapedFirmware]] = None

    def _page_url(self, page: int) -> str:
        return self.RELEASES_API.format(per_page=self.PER_PAGE, page=page)

    def _parse_releases(self, body: str) -> List[ScrapedFirmware]:
        versions: List[ScrapedFirmware] = []
        for release in json.loads(body):
            tag = (release.get("tag_name") or "").strip()
            if release.get("draft") or release.get("prerelease") or not self.STABLE_TAG.match(tag):
                continue
            published = release.get("published_at")
            try:
                released = datetime.strptime(published, "%Y-%m-%dT%H:%M:%SZ") if published else None
            except ValueError:
                released = None
            versions.append(ScrapedFirmware(
                version=tag,
                release_date=released,
                download_url=release.get("html_url"),
                changelog=(release.get("body") or "").strip() or None,
            ))
        return versions

    async def _load(self) -> Optional[List[ScrapedFirmware]]:
        if self._versions is not None:
            return self._versions

        versions: List[ScrapedFirmware] = []
        for page in range(1, self.MAX_PAGES + 1):
            body = await self.fetch_page(self._page_url(page))
            if body is None:
                logger.warning("OBS releases page %d did not load", page)
                return None
            try:
                count = len(json.loads(body))
                versions.extend(self._parse_releases(body))
            except (ValueError, TypeError):
                logger.warning("OBS releases page %d was not a release list", page)
                return None
            if count < self.PER_PAGE:
                break

        self._versions = versions or None
        return self._versions

    async def fetch_device_list(self) -> ScraperResult:
        if await self._load() is None:
            return ScraperResult(success=False, error="Could not read OBS Studio's GitHub releases")
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=self.PRODUCT_NAME,
                    category="vst_plugin",
                    firmware_page_url=self.PRODUCT_URL,
                    product_url=self.PRODUCT_URL,
                )
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        versions = await self._load()
        if versions is None:
            return ScraperResult(success=False, error="Could not read OBS Studio's GitHub releases")
        if device_name != self.PRODUCT_NAME:
            return ScraperResult(success=True, firmware_versions=[])
        return ScraperResult(success=True, firmware_versions=list(versions))
