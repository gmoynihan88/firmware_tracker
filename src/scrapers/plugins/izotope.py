import re
from datetime import datetime
from typing import Dict, List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class IZotopeScraper(BaseScraper):
    """Scraper for iZotope plugins.

    Each release-notes page covers a product line and tier, and lists every major
    version it has shipped. Products are therefore modelled per major -- "Ozone 11"
    and "Ozone 12" are separate, as Pianoteq 8 and 9 are -- because a major is a paid
    upgrade rather than an update. Reporting 12.1.0 to someone running Ozone 11 would
    be an advert, not a notification.

    There is no index to discover pages from: /products/release-notes.html redirects
    to a product page and exposes no links. The slugs below were each confirmed
    against the live site, and a deliberately impossible slug 404s, so a page that
    loads is a page that exists.

    Known limitation: iZotope's numbering is not always monotonic. Insight lists
    "2.10" released February 2019 alongside "2.6.0" released April 2025. This scraper
    orders by date and reports 2.6.0, but sync_firmware_for_device recomputes
    is_latest numerically and will store 2.10. That numeric rule is right for every
    other manufacturer here -- TAL's shipping versions carry no date at all, so
    ordering those by date would rank an old changelog entry above the current build
    -- so the app is not changed to suit one product.
    """

    manufacturer_name = "iZotope"
    manufacturer_slug = "izotope"
    manufacturer_website = "https://www.izotope.com"

    RELEASE_NOTES_URL = "https://www.izotope.com/en/products/release-notes/{slug}.html"

    # (product line, slug, tier suffix). VocalSynth has no release-notes page under
    # any slug tried, so it is deliberately absent rather than guessed at.
    RELEASE_PAGES = [
        ("Ozone", "ozone-standard-release-notes", ""),
        ("Ozone", "ozone-elements-release-notes", " Elements"),
        ("Ozone", "ozone-advanced-release-notes", " Advanced"),
        ("RX", "rx-standard-release-notes", ""),
        ("RX", "rx-elements-release-notes", " Elements"),
        ("RX", "rx-advanced-release-notes", " Advanced"),
        ("Nectar", "nectar-release-notes", ""),
        ("Neutron", "neutron-release-notes", ""),
        ("Trash", "trash-release-notes", ""),
        ("Insight", "insight-release-notes", ""),
    ]

    # "Version 12.1.0 released December 1, 2025". Anchored on both words because the
    # same pages quote OS and host versions -- "macOS Ventura (13.7)", "Logic Pro
    # 10.8 - 11" -- which a looser pattern would read as releases.
    RELEASE = re.compile(
        r"^Version\s+(\d+(?:\.\d+)+)\s+released\s+([A-Z][a-z]+\s+\d{1,2},\s*\d{4})$"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pages: Dict[str, List[ScrapedFirmware]] = {}

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(p) for p in re.findall(r"\d+", version)) or (0,)

    def _parse_releases(self, html: str) -> List[ScrapedFirmware]:
        """Read every "Version X released DATE" line from a release-notes page."""
        releases: List[ScrapedFirmware] = []
        seen = set()

        for line in self.parse_html(html).get_text("\n").splitlines():
            match = self.RELEASE.match(line.strip())
            if not match:
                continue

            version, date_text = match.groups()
            if version in seen:
                continue

            release_date = None
            for fmt in ("%B %d, %Y", "%b %d, %Y"):
                try:
                    release_date = datetime.strptime(re.sub(r"\s+", " ", date_text), fmt)
                    break
                except ValueError:
                    continue

            seen.add(version)
            releases.append(ScrapedFirmware(version=version, release_date=release_date))

        # Order by release date, not by version arithmetic. iZotope's own numbering
        # is not always monotonic: Insight lists "2.10" released February 2019 and
        # "2.6.0" released April 2025, so comparing the numbers puts a six-year-old
        # build on top. Releases are filtered to one major before this matters, and
        # within a major the date is the reliable signal. Version order is the
        # fallback for entries with no parseable date.
        return sorted(
            releases,
            key=lambda fw: (
                fw.release_date is not None,
                fw.release_date or datetime.min,
                self._version_key(fw.version),
            ),
            reverse=True,
        )

    async def _get_page(self, slug: str) -> Optional[List[ScrapedFirmware]]:
        """Fetch and parse one release-notes page, once per scraper instance."""
        if slug in self._pages:
            return self._pages[slug]

        html = await self.fetch_page_js(
            self.RELEASE_NOTES_URL.format(slug=slug), wait_for_timeout=25000
        )
        if not html:
            return None

        text = self.parse_html(html).get_text(" ", strip=True)[:300].lower()
        if "404" in text or "not found" in text:
            return None

        releases = self._parse_releases(html)
        if not releases:
            return None

        self._pages[slug] = releases
        return releases

    def _resolve(self, device_name: str) -> Optional[tuple]:
        """Map a device name back to its page and major version."""
        for line, slug, suffix in self.RELEASE_PAGES:
            match = re.fullmatch(rf"{re.escape(line)}\s+(\d+){re.escape(suffix)}", device_name)
            if match:
                return slug, match.group(1)
        return None

    async def fetch_device_list(self) -> ScraperResult:
        """One device per major version found on each page.

        Discovered rather than hardcoded: a new major appears as a new product the
        first time iZotope publishes notes for it.
        """
        devices = []
        for line, slug, suffix in self.RELEASE_PAGES:
            releases = await self._get_page(slug)
            if not releases:
                continue

            url = self.RELEASE_NOTES_URL.format(slug=slug)
            for major in sorted({fw.version.split(".")[0] for fw in releases}, key=int):
                devices.append(
                    ScrapedDevice(
                        name=f"{line} {major}{suffix}",
                        category="vst_plugin",
                        firmware_page_url=url,
                        product_url=url,
                    )
                )

        if not devices:
            return ScraperResult(
                success=False, error="No iZotope release-notes pages could be read"
            )

        return ScraperResult(success=True, devices=devices)

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        resolved = self._resolve(device_name)
        if not resolved:
            return ScraperResult(
                success=False,
                error=f"No iZotope release-notes page is configured for {device_name}",
            )

        slug, major = resolved
        releases = await self._get_page(slug)
        if releases is None:
            return ScraperResult(
                success=False,
                error=f"Could not read {self.RELEASE_NOTES_URL.format(slug=slug)}",
            )

        # Only this major: a newer one is a paid upgrade, not an available update.
        for_major = [fw for fw in releases if fw.version.split(".")[0] == major]
        if not for_major:
            return ScraperResult(
                success=False,
                error=f"{device_name} has no releases listed for version {major}",
            )

        return ScraperResult(success=True, firmware_versions=for_major)
