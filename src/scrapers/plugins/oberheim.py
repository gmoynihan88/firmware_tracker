import json
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class OberheimScraper(BaseScraper):
    """Oberheim -- TEO-5, OB-X8 and OB-6 OS releases from the support page.

    oberheim.com/support/ has one Elementor section per synth, headed "<Product> Support",
    and each links its current OS as a download:

        <h2>OB-6 Support</h2> ... <a href=".../2024/02/OB-6_OS-1.8.0.zip">
          <span class="elementor-icon-list-text">Latest OB-6 OS — v1.8.0</span></a>

    **The version comes from the file, then the label.** Zoom's link text went stale while
    its files did not, so the zip's own name is trusted first.

    **Only the "Latest ... OS" link is a release.** Each section also links things that
    carry versions and are not the OS: "TEO-5 Poly Chain OS BETA — v1.2.0.15" (a beta,
    skipped), "OB-6 Factory Programs — v1.0" and "OB-6 Alternative Tunings — v1.0" (sound
    banks), and "Manual Addendum v2.0" / "OB-6-Manual-Addendum-OS-v1.6.6.pdf" (documents).
    A sentence also names the version -- "The newest version of the TEO-5 Main OS is
    TEO-5_Main_v1.1.0.4", "The current version is Main 1.8.0" -- written three ways across
    three sections, so the link is read rather than the prose.

    **OB-X8 alone has history.** Its section links "OB-X8 OS — v2.0.0.1 Changelog", a text
    file of "OBX8 Main 2.0.0.1 Changelog" entries back to 1.1.0.0. It is undated.

    **Dates come only from news posts that name the version.** The WordPress posts API
    has "Free OB-X8 OS v2.0 Update Delivers Powerful New Features", dated 2024-07-02 and
    announcing the update as available -- that dates the changelog's 2.0.0.0. "TEO-5 Poly
    Chain OS Update Now Available" (2025-11-06) names no version, and the Poly Chain OS is
    the one the support page still labels BETA, so it dates nothing. The posts are
    optional: if they fail to load, the releases are stored undated.

    Ruled out, checked 2026-09-15: the ``wp-content/uploads/2024/08/`` folder in each
    download URL is the upload month, not a release date; support.oberheim.com (Zendesk)
    has "Updating the OS" articles that link back to /support/ and name no version.
    """

    manufacturer_name = "Oberheim"
    manufacturer_slug = "oberheim"
    manufacturer_website = "https://oberheim.com"

    BASE_URL = "https://oberheim.com"
    SUPPORT_URL = BASE_URL + "/support/"
    POSTS_URL = BASE_URL + "/wp-json/wp/v2/posts?search=OS&per_page=100&_fields=date,title"

    SECTION = re.compile(r"^(?P<name>\S.*?)\s+Support$")
    LATEST = re.compile(r"^Latest\s+.+?\s+OS\s*[—–-]\s*v?(?P<version>\d+(?:\.\d+)+)$", re.I)
    FILE_VERSION = re.compile(r"(\d+(?:\.\d+)+)\.zip$", re.I)
    CHANGELOG_ENTRY = re.compile(r"^\S+\s+Main\s+(?P<version>\d+(?:\.\d+)+)\s+Changelog\s*$", re.M)
    POST_TITLE = re.compile(r"^(?:.*?\s)?(?P<product>\S+)\s+OS\s+v(?P<version>\d+(?:\.\d+)+)\b", re.I)
    NOTES_LIMIT = 4000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._devices: Optional[Dict[str, List[ScrapedFirmware]]] = None

    # --- parsing ------------------------------------------------------------

    @staticmethod
    def _text(element) -> str:
        return " ".join(element.get_text(" ").split())

    def _parse_support(self, html: str) -> Dict[str, Tuple[str, Optional[str]]]:
        """Product name -> (current OS version, changelog URL or None)."""
        sections: Dict[str, Tuple[str, Optional[str]]] = {}
        for heading in self.parse_html(html).find_all("h2"):
            matched = self.SECTION.match(self._text(heading))
            if not matched:
                continue
            version: Optional[str] = None
            changelog: Optional[str] = None
            for element in heading.find_all_next():
                if element.name == "h2":
                    break
                if element.name != "a" or not element.get("href"):
                    continue
                label, href = self._text(element), element["href"]
                latest = self.LATEST.match(label)
                if latest and version is None:
                    from_file = self.FILE_VERSION.search(href.split("?")[0])
                    version = from_file.group(1) if from_file else latest.group("version")
                elif re.search(r"\bChangelog\b", label, re.I) and href.lower().endswith(".txt"):
                    changelog = urljoin(self.BASE_URL, href)
            if version:
                sections.setdefault(matched.group("name"), (version, changelog))
        return sections

    def _parse_changelog(self, text: str) -> List[ScrapedFirmware]:
        heads = list(self.CHANGELOG_ENTRY.finditer(text))
        releases: List[ScrapedFirmware] = []
        for index, head in enumerate(heads):
            end = heads[index + 1].start() if index + 1 < len(heads) else len(text)
            lines = [line.strip() for line in text[head.end():end].splitlines()]
            notes = "\n".join(line for line in lines if line and not re.fullmatch(r"-{3,}", line))
            releases.append(ScrapedFirmware(version=head.group("version"), release_date=None,
                                            changelog=notes[: self.NOTES_LIMIT] or None))
        return releases

    @staticmethod
    def _version_key(version: str) -> Tuple[int, ...]:
        parts = [int(part) for part in version.split(".")]
        while len(parts) > 1 and parts[-1] == 0:
            parts.pop()
        return tuple(parts)

    def _parse_posts(self, body: str) -> Dict[Tuple[str, Tuple[int, ...]], datetime]:
        """(product, version key) -> publication date, from posts whose title names an OS version."""
        try:
            posts = json.loads(body)
        except ValueError:
            return {}
        dates: Dict[Tuple[str, Tuple[int, ...]], datetime] = {}
        for post in posts if isinstance(posts, list) else []:
            title = " ".join(self.parse_html((post.get("title") or {}).get("rendered") or "").get_text(" ").split())
            matched = self.POST_TITLE.match(title)
            if not matched or re.search(r"\bbeta\b", title, re.I) or not post.get("date"):
                continue
            key = (matched.group("product"), self._version_key(matched.group("version")))
            dates.setdefault(key, datetime.strptime(post["date"][:10], "%Y-%m-%d"))
        return dates

    # --- loading ------------------------------------------------------------

    async def _load(self) -> Optional[Dict[str, List[ScrapedFirmware]]]:
        if self._devices is not None:
            return self._devices
        html = await self.fetch_page(self.SUPPORT_URL)
        sections = self._parse_support(html) if html else {}
        if not sections:
            return None
        posts = await self.fetch_page(self.POSTS_URL)
        dates = self._parse_posts(posts) if posts else {}
        if not posts:
            logger.warning("Oberheim news posts did not load; releases stored undated")
        devices: Dict[str, List[ScrapedFirmware]] = {}
        for name, (current, changelog_url) in sections.items():
            releases: List[ScrapedFirmware] = []
            if changelog_url:
                text = await self.fetch_page(changelog_url)
                releases = self._parse_changelog(text) if text else []
                if not text:
                    logger.warning("Oberheim changelog %s did not load", changelog_url)
            if current not in {release.version for release in releases}:
                releases.insert(0, ScrapedFirmware(version=current, release_date=None))
            for release in releases:
                release.release_date = dates.get((name, self._version_key(release.version)))
            devices[name] = releases
        self._devices = devices
        return devices

    async def fetch_device_list(self) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error="Oberheim support page named no current OS")
        return ScraperResult(
            success=True,
            devices=[ScrapedDevice(name=name, category="synthesizer", firmware_page_url=self.SUPPORT_URL,
                                   product_url=self.SUPPORT_URL) for name in devices],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error="Oberheim support page named no current OS")
        return ScraperResult(success=True, firmware_versions=devices.get(device_name, []))
