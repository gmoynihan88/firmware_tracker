import json
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class AppleScraper(BaseScraper):
    """Apple's music apps -- Logic Pro and MainStage -- from the App Store and Apple Support.

    **The App Store lookup API** answers for both apps without a key and states the
    current version, the day it shipped and its notes:

        GET https://itunes.apple.com/lookup?id=634148309&country=us
        {"results": [{"version": "12.3.1", "currentVersionReleaseDate": "2026-08-13T16:59:07Z",
                      "releaseNotes": "This update includes stability improvements ..."}]}

    It knows nothing earlier, so that is all MainStage gets: Apple publishes no
    MainStage release notes page.

    **Logic Pro's history is on Apple Support**, one release-notes article per major
    version since 10.0, each release under its own heading with the notes below it:

        <h2 class="gb-header">New in Logic Pro 12.3.1</h2>
        <h3 class="gb-header">Logic Pro for Mac 12.3</h3> <p>...</p> <ul>...</ul>

    The headings change wording across thirteen years -- "New in Logic Pro 12.3.1",
    "Logic 11.2", "Logic Pro X 10.0.6 update" -- so the pattern allows each part but
    must see a version. The page's own title ("Logic Pro for Mac 10.8 release notes")
    is an `h1` and is not a release. "Logic Pro for iPad" is a different app and is
    not read.

    **The articles are listed here rather than discovered.** Their cross-links differ
    from one article to the next -- some end in "Previous versions", some in "Learn
    more" -- and a fixed list cannot be led to an unrelated page. The 12 article is
    the one that grows; the others are archives. Any of them failing to load fails the
    scrape, so a history with a hole in it is never stored as complete.

    **Only the current version has a date.** The articles date nothing: "Published
    Date: August 14, 2026" at the foot of each is the article's, not a release's. So
    every earlier release is stored undated, and the current one takes the App Store's
    date. When the App Store is ahead of the article, the release is stored from the
    App Store alone.
    """

    manufacturer_name = "Apple"
    manufacturer_slug = "apple"
    manufacturer_website = "https://www.apple.com"

    LOOKUP_URL = "https://itunes.apple.com/lookup?id={app_id}&country=us"
    LOGIC = "Logic Pro"
    MAINSTAGE = "MainStage"
    APPS = {
        LOGIC: (634148309, "https://apps.apple.com/us/app/logic-pro/id634148309"),
        MAINSTAGE: (634159523, "https://apps.apple.com/us/app/mainstage/id634159523"),
    }
    RELEASE_NOTES_URLS = [
        "https://support.apple.com/en-us/HT203718",  # 12.x, current
        "https://support.apple.com/en-us/126835",  # 11.x
        "https://support.apple.com/en-us/120134",  # 10.8
        "https://support.apple.com/en-us/106014",  # 10.7
        "https://support.apple.com/kb/HT213052",  # 10.6
        "https://support.apple.com/kb/HT213051",  # 10.5
        "https://support.apple.com/kb/HT211160",  # 10.4
        "https://support.apple.com/kb/HT208471",  # 10.3
        "https://support.apple.com/kb/HT207473",  # 10.2
        "https://support.apple.com/kb/HT204983",  # 10.1
        "https://support.apple.com/kb/HT204982",  # 10.0
    ]
    RELEASE_HEADING = re.compile(
        r"^(?:New\s+in\s+)?Logic(?:\s+Pro)?(?:\s+X)?(?:\s+for\s+Mac)?\s+(?P<version>\d{1,2}\.\d+(?:\.\d+)?)(?:\s+update)?$",
        re.I,
    )
    NOTES_LIMIT = 8000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._products: Optional[Dict[str, List[ScrapedFirmware]]] = None

    def _parse_lookup(self, body: str) -> Optional[ScrapedFirmware]:
        try:
            results = json.loads(body).get("results") or []
        except (ValueError, AttributeError):
            return None
        if not results or not results[0].get("version"):
            return None
        app = results[0]
        try:
            released = datetime.strptime(app.get("currentVersionReleaseDate") or "", "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            released = None
        return ScrapedFirmware(
            version=app["version"].strip(),
            release_date=released,
            changelog=(app.get("releaseNotes") or "").strip() or None,
        )

    def _parse_release_notes(self, html: str) -> List[ScrapedFirmware]:
        soup = self.parse_html(html)
        versions: List[ScrapedFirmware] = []
        for heading in soup.find_all(["h2", "h3"]):
            matched = self.RELEASE_HEADING.match(" ".join(heading.get_text(" ").split()))
            if not matched:
                continue
            notes: List[str] = []
            for sibling in heading.find_next_siblings():
                if sibling.name not in ("p", "ul", "ol"):
                    break  # the next heading, or the article's "Published Date" footer
                parts = sibling.find_all("li") if sibling.name in ("ul", "ol") else [sibling]
                notes.extend(
                    ("- " if part.name == "li" else "") + " ".join(part.get_text(" ").split())
                    for part in parts if part.get_text(strip=True)
                )
            versions.append(ScrapedFirmware(
                version=matched.group("version"),
                changelog="\n".join(notes)[: self.NOTES_LIMIT] or None,
            ))
        return versions

    async def _lookup(self, name: str) -> Optional[ScrapedFirmware]:
        body = await self.fetch_page(self.LOOKUP_URL.format(app_id=self.APPS[name][0]))
        return self._parse_lookup(body) if body else None

    async def _load(self) -> Optional[Dict[str, List[ScrapedFirmware]]]:
        if self._products is not None:
            return self._products

        history: Dict[str, ScrapedFirmware] = {}
        for url in self.RELEASE_NOTES_URLS:
            html = await self.fetch_page(url)
            releases = self._parse_release_notes(html) if html else []
            if not releases:
                logger.warning("Logic Pro release notes at %s did not load or had no releases", url)
                return None
            for release in releases:
                history.setdefault(release.version, release)

        products: Dict[str, List[ScrapedFirmware]] = {}
        current = await self._lookup(self.LOGIC)
        if current is not None:
            documented = history.get(current.version)
            history[current.version] = ScrapedFirmware(
                version=current.version,
                release_date=current.release_date,
                changelog=documented.changelog if documented and documented.changelog else current.changelog,
            )
        products[self.LOGIC] = list(history.values())

        mainstage = await self._lookup(self.MAINSTAGE)
        if mainstage is not None:
            products[self.MAINSTAGE] = [mainstage]

        self._products = products
        return self._products

    async def fetch_device_list(self) -> ScraperResult:
        products = await self._load()
        if products is None:
            return ScraperResult(success=False, error="Could not read Logic Pro's release notes on Apple Support")
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category="vst_plugin",
                    firmware_page_url=self.RELEASE_NOTES_URLS[0] if name == self.LOGIC else url,
                    product_url=url,
                )
                for name, (_app_id, url) in self.APPS.items()
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        products = await self._load()
        if products is None:
            return ScraperResult(success=False, error="Could not read Logic Pro's release notes on Apple Support")
        if device_name not in self.APPS:
            return ScraperResult(success=True, firmware_versions=[])
        if device_name not in products:
            return ScraperResult(success=False, error=f"The App Store did not answer for {device_name}")
        return ScraperResult(success=True, firmware_versions=list(products[device_name]))
