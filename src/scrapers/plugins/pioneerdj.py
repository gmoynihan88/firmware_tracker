import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)

MONTHS = {name: number for number, name in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


class PioneerDJScraper(BaseScraper):
    """Pioneer DJ (AlphaTheta) -- firmware from the news posts on each product page.

    Pioneer DJ publishes no firmware list. Its help centre's article API is closed,
    and download pages give a file but no version. What every product page does carry
    is a "related news" strip, back to 2015, and firmware releases are news posts:

        <a href="/en/news/2025/cdj-3000-firmware-update-320/">
          <p class="...subTitle">24 April, 2025</p>
          <p class="...title">Update: CDJ-3000 Firmware Ver. 3.20</p></a>

    So the scraper lists products from each gear category page, reads each product's
    strip, and keeps the posts that are firmware releases. 192 product pages carry the
    DJ gear; 107 of them had a firmware post on 2026-09-14.

    **A device is the model the post names, not the product page.** Colour variants
    have pages of their own -- `cdj-3000-w`, `ddj-sb-l`, `xdj-xz-n` -- carrying their
    base model's posts, which say "CDJ-3000". The page's slug is matched against the
    title, dropping trailing parts until it matches, and the title's model is the device.

    **Titles are written a dozen ways**: "Update: CDJ-3000 Firmware Ver. 3.20",
    "XDJ-RX Firmware update (Ver.2.20)", "TORAIZ SP-16 firmware update (ver 1.50)
    introduces live sampling", "Major CDJ-3000 firmware update – ver. 2.0 –". Rules:

    - The title must say firmware. Driver and plug-in releases are not firmware.
    - "TORAIZ SP-16 Ver.1.4 firmware update postponed" and notices are not releases.
    - A version after "Driver" belongs to the driver: "XDJ-RX2 Firmware update
      (Ver.1.32) / Driver for Windows update (Ver.1.020)".
    - Several models and several versions pair in order: "CDJ-2000NXS2 / DJM-900NXS2
      Firmware update (Ver.1.40 / Ver.1.30)". Several models and one version share it:
      "DJM-V10/DJM-V10-LF Firmware Ver. 1.16".
    - A model inside a longer one is not that model: DDJ-FLX6 is not DDJ-FLX6-GT.

    **Since 2020 most titles give no version** -- "Update: XDJ-RX2 firmware",
    "Updates: XDJ-XZ, XDJ-RX3, XDJ-RR, and XDJ-RX2 firmware updates" -- and for 20
    products the newest firmware post is one of those. The post itself states each
    model's version ("XDJ-RX2 Firmware ver. 1.42 Download page"), so a versionless
    firmware post is opened and read. A post that states none is skipped rather than
    guessed.

    The date is the post's. A page that fails to load is skipped with a warning; its
    devices keep what they had.
    """

    manufacturer_name = "Pioneer DJ"
    manufacturer_slug = "pioneerdj"
    manufacturer_website = "https://www.pioneerdj.com"

    BASE_URL = "https://www.pioneerdj.com"
    CATEGORY_URL = BASE_URL + "/en/product/{category}/"
    CATEGORIES = {
        "dj-players-turntables": "other",
        "dj-mixers": "other",
        "all-in-one-dj-systems": "midi_controller",
        "dj-controllers": "midi_controller",
        "software-interfaces": "other",
        "dj-samplers": "synthesizer",
        "dj-effectors": "other",
        "music-production": "synthesizer",
    }

    DATE = re.compile(r"^(\d{1,2})\s+([A-Za-z]+)\.?,?\s+(\d{4})$")
    VERSION = re.compile(r"\bver(?:sion)?\.?\s*(\d+(?:\.\d+)+)", re.I)
    NOT_A_RELEASE = re.compile(r"postpone|planned|notice|beta|coming", re.I)
    NAMES_SPLIT = re.compile(r"\s*(?:/|,|&|\band\b)\s*", re.I)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._models: Optional[Dict[str, Tuple[str, str, List[ScrapedFirmware]]]] = None
        self._articles: Dict[str, Optional[str]] = {}

    # --- parsing ------------------------------------------------------------

    def _date(self, text: str) -> Optional[datetime]:
        matched = self.DATE.match(text)
        if not matched:
            return None
        month = MONTHS.get(matched.group(2)[:3].lower())
        try:
            return datetime(int(matched.group(3)), month, int(matched.group(1))) if month else None
        except ValueError:
            return None

    def _parse_listing(self, html: str, category: str) -> List[str]:
        """Product page URLs from a category page, in order."""
        pattern = re.compile(rf"^(?:{re.escape(self.BASE_URL)})?/en/product/{re.escape(category)}/([^/?#]+)/$")
        urls: List[str] = []
        for link in self.parse_html(html).find_all("a", href=True):
            matched = pattern.match(link["href"].split("?")[0])
            if matched:
                url = self.CATEGORY_URL.format(category=category) + matched.group(1) + "/"
                if url not in urls:
                    urls.append(url)
        return urls

    def _parse_news(self, html: str) -> List[Tuple[datetime, str, str]]:
        """(date, title, post URL) for each post in a product page's news strip."""
        posts = []
        for paragraph in self.parse_html(html).find_all("p"):
            released = self._date(" ".join(paragraph.get_text(" ").split()))
            title = paragraph.find_next_sibling("p") if released else None
            link = paragraph.find_parent("a", href=True) if title else None
            if link is None:
                continue
            href = link["href"]
            posts.append((released, " ".join(title.get_text(" ").split()),
                          href if href.startswith("http") else self.BASE_URL + href))
        return posts

    @staticmethod
    def _model_pattern(parts: List[str]) -> re.Pattern:
        # "toraiz-sp-16" matches "TORAIZ SP-16"; "ddj-flx6" does not match inside "DDJ-FLX6-GT".
        return re.compile(
            r"(?<![A-Za-z0-9])" + r"[\s\-]*".join(map(re.escape, parts)) + r"(?![A-Za-z0-9]|-[A-Za-z0-9])", re.I)

    def _model_in(self, slug: str, text: str) -> Optional[re.Match]:
        """Where the page's model is named in a title, dropping colour suffixes off the slug."""
        parts = slug.split("-")
        for keep in range(len(parts), 1, -1):
            matched = self._model_pattern(parts[:keep]).search(text)
            if matched:
                return matched
        return self._model_pattern(parts).search(text) if len(parts) == 1 else None

    def _title_version(self, title: str, model: re.Match) -> Optional[str]:
        """The model's version as the title states it, or None when the title states none."""
        lowered = title.lower()
        firmware_at = lowered.find("firmware")
        driver_at = lowered.find("driver", firmware_at)
        stated = title[: driver_at] if driver_at > firmware_at >= 0 else title
        versions = self.VERSION.findall(stated)
        if len(versions) <= 1:
            return versions[0] if versions else None

        head = re.sub(r"^Updates?\s*:\s*", "", title[: firmware_at] if firmware_at >= 0 else title, flags=re.I)
        names = [name for name in self.NAMES_SPLIT.split(head) if name.strip()]
        if len(names) != len(versions):
            return None
        for name, version in zip(names, versions):
            if model.group(0).lower() in name.lower():
                return version
        return None

    def _article_version(self, html: str, model: str) -> Optional[str]:
        """A model's version as a versionless post's body states it: "XDJ-RX2 Firmware ver. 1.42"."""
        soup = self.parse_html(html)
        text = " ".join((soup.find("main") or soup).get_text(" ").split())
        parts = re.split(r"[\s\-]+", model)
        pattern = re.compile(self._model_pattern(parts).pattern + r"\s+Firmware\s+ver(?:sion)?\.?\s*(\d+(?:\.\d+)+)", re.I)
        found = {matched.group(1) for matched in pattern.finditer(text)}
        return found.pop() if len(found) == 1 else None

    # --- loading ------------------------------------------------------------

    async def _article(self, url: str) -> Optional[str]:
        if url not in self._articles:
            self._articles[url] = await self.fetch_page(url)
        return self._articles[url]

    async def _load(self) -> Optional[Dict[str, Tuple[str, str, List[ScrapedFirmware]]]]:
        if self._models is not None:
            return self._models

        pages: List[Tuple[str, str]] = []
        for category in self.CATEGORIES:
            html = await self.fetch_page(self.CATEGORY_URL.format(category=category))
            if html:
                pages.extend((category, url) for url in self._parse_listing(html, category))
            else:
                logger.warning("Pioneer DJ category %s did not load", category)

        models: Dict[str, Tuple[str, str, Dict[str, ScrapedFirmware]]] = {}
        for category, page_url in pages:
            html = await self.fetch_page(page_url)
            if not html:
                logger.warning("Pioneer DJ product page %s did not load", page_url)
                continue
            slug = page_url.rstrip("/").rsplit("/", 1)[-1]
            for released, title, post_url in self._parse_news(html):
                if "firmware" not in title.lower() or self.NOT_A_RELEASE.search(title):
                    continue
                model = self._model_in(slug, title)
                if model is None:
                    continue  # a post about another product
                name = " ".join(model.group(0).upper().split())
                version = self._title_version(title, model)
                if version is None and not self.VERSION.search(title):
                    article = await self._article(post_url)
                    version = self._article_version(article, name) if article else None
                if version is None:
                    continue

                entry = models.setdefault(name, [self.CATEGORIES[category], page_url, {}])
                if slug == "-".join(re.split(r"[\s\-]+", name.lower())):
                    entry[1] = page_url  # the model's own page rather than a colour variant's
                existing = entry[2].get(version)
                if existing is None or released < existing.release_date:
                    entry[2][version] = ScrapedFirmware(
                        version=version, release_date=released, download_url=post_url, changelog=title,
                    )

        self._models = {
            name: (category, url, sorted(versions.values(), key=lambda fw: fw.release_date, reverse=True))
            for name, (category, url, versions) in models.items()
        } or None
        return self._models

    async def fetch_device_list(self) -> ScraperResult:
        models = await self._load()
        if not models:
            return ScraperResult(success=False, error="No Pioneer DJ firmware posts found on its product pages")
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(name=name, category=category, firmware_page_url=url, product_url=url)
                for name, (category, url, _versions) in sorted(models.items())
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        models = await self._load()
        if not models:
            return ScraperResult(success=False, error="No Pioneer DJ firmware posts found on its product pages")
        _category, _url, versions = models.get(device_name, (None, None, []))
        return ScraperResult(success=True, firmware_versions=list(versions))
