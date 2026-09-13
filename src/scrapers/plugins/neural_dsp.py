import re
from datetime import datetime
from typing import List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class NeuralDSPScraper(BaseScraper):
    """Neural DSP Quad Cortex, read from the announcement posts on its updates page.

    There is no downloads page. Neural announces each CorOS release as a post, and
    `/us/quad-cortex-updates` lists them with their dates:

        coros-4-0-1-and-cortex-control-4-0-1-are-now-available    March 4, 2026
        coros-3-3-1-and-cortex-control-1-4-1-are-now-available    December 15, 2025

    The version lives in the slug, which is a weaker source than markup and is why
    this scraper is narrow: it reads the index only, takes the version from the slug
    and the date from the card beside it, and does not open the posts.

    **Every post names two versions and only one is the device's.** CorOS is the Quad
    Cortex's firmware; Cortex Control is the desktop editor. On older releases they
    are plainly different -- CorOS 3.3.1 shipped with Cortex Control 1.4.1 -- and on
    recent ones they have converged, so `coros-4-0-1-and-cortex-control-4-0-1` states
    the same number twice. That convergence is what makes taking the wrong one
    invisible today and wrong again the moment they diverge, so the pattern anchors
    on the `coros-` prefix and stops at `-and-`.

    Neural writes the slug two ways, and both appear:

        coros-4-0-1-and-cortex-control-4-0-1-are-now-available   version after coros-
        coros-and-cortex-control-4-1-0-are-now-available         one version for both

    **Not every post is a release.** The same index carries
    `coros-3-0-0-release-schedule`, `how-to-update-to-coros-3-0-0` and a long run of
    `quad-cortex-development-update-NN` posts, several of which name a version that
    had not shipped yet. Requiring `are-now-available` is what separates an
    announcement from a plan.

    One product. CorOS runs on Quad Cortex, and the Nano and Mini Cortex have their
    own lines that this page does not cover, so they are absent rather than listed
    against the wrong firmware.
    """

    manufacturer_name = "Neural DSP"
    manufacturer_slug = "neuraldsp"
    manufacturer_website = "https://neuraldsp.com"

    UPDATES_URL = "https://neuraldsp.com/us/quad-cortex-updates"
    PRODUCT_NAME = "Quad Cortex"

    # "coros-4-0-1-and-..." and "coros-and-cortex-control-4-1-0-...", both requiring
    # the post to announce a shipped release.
    RELEASE_SLUG = re.compile(
        r"^coros-(?:and-cortex-control-)?(\d+)-(\d+)-(\d+).*are-now-available", re.I
    )
    POST_DATE = re.compile(
        r"(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+(\d{1,2}),\s+(\d{4})"
    )
    MONTHS = {month: index for index, month in enumerate(
        ["january", "february", "march", "april", "may", "june", "july",
         "august", "september", "october", "november", "december"], start=1)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._versions: Optional[List[ScrapedFirmware]] = None

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(part) for part in re.findall(r"\d+", version)) or (0,)

    def _parse_index(self, html: str) -> List[ScrapedFirmware]:
        soup = self.parse_html(html)
        found: dict = {}

        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            if "quad-cortex-updates/" not in href:
                continue
            slug = href.rstrip("/").rsplit("/", 1)[-1]
            matched = self.RELEASE_SLUG.match(slug)
            if not matched:
                continue

            version = ".".join(matched.groups())
            if version in found:
                continue

            release_date = None
            card = anchor.find_parent(["article", "li", "div"])
            if card is not None:
                dated = self.POST_DATE.search(card.get_text(" ", strip=True))
                if dated:
                    month, day, year = dated.groups()
                    try:
                        release_date = datetime(
                            int(year), self.MONTHS[month.lower()], int(day)
                        )
                    except (ValueError, KeyError):
                        release_date = None

            found[version] = ScrapedFirmware(version=version, release_date=release_date)

        return sorted(
            found.values(), key=lambda fw: self._version_key(fw.version), reverse=True
        )

    async def _load(self) -> Optional[List[ScrapedFirmware]]:
        if self._versions is not None:
            return self._versions
        html = await self.fetch_page(self.UPDATES_URL)
        if not html:
            return None
        versions = self._parse_index(html)
        if not versions:
            return None
        self._versions = versions
        return versions

    async def fetch_device_list(self) -> ScraperResult:
        versions = await self._load()
        if versions is None:
            return ScraperResult(
                success=False, error=f"No CorOS releases found at {self.UPDATES_URL}"
            )

        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=self.PRODUCT_NAME,
                    category="guitar_pedal",
                    firmware_page_url=self.UPDATES_URL,
                    product_url=self.UPDATES_URL,
                )
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        versions = await self._load()
        if versions is None:
            return ScraperResult(
                success=False, error=f"No CorOS releases found at {self.UPDATES_URL}"
            )
        if device_name != self.PRODUCT_NAME:
            return ScraperResult(success=True, firmware_versions=[])
        return ScraperResult(success=True, firmware_versions=versions)
