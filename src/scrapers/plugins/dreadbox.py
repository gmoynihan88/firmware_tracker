import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class DreadboxScraper(BaseScraper):
    """Dreadbox synths, from the firmware downloads on the support page.

    dreadbox-fx.com answers plain requests with 403 and renders for a browser, so every
    page is rendered. robots.txt allows everything but the shop's internals.

    **The support page is one row per product**, a `div.row-inner` whose first column's
    h3 names it and whose icon boxes pair a label with a download:

        <h3>Typhon</h3> ... <h3>Typhon Updater 4.2.1 MacOS</h3><a href=".../Typhon-Updater-4.2.1-macOS.zip">
        <h3>Erebus v3</h3> ... <h3>Firmware</h3><a href=".../ErebusV3_Firmware-_V1_01.zip">

    An outer row wraps every product row, and its first heading is "Abyss", so a
    download belongs to its *nearest* row -- taking the outermost filed every firmware
    file under Abyss. Six products on 2026-09-15: Artemis, Erebus v3, Murmux Adept,
    Nymphes, Nyx v2 and Typhon.

    A download is firmware when its label says firmware or updater. Its version comes
    from the label ("Firmware Update 1.2.0") or, when the label is only "Firmware", from
    the file name -- "ErebusV3_Firmware-_V1_01.zip" is 1.01, and the "V3" in the name is
    the model. "Factory Firmware" is a presets archive with no version, and is skipped.

    **Dates come from the news posts, where one exists.** The upload month in each file's
    path is not a release date: Erebus, Murmux 1.1, Nymphes and Nyx were all uploaded in
    April 2025, when the site moved, and Murmux 1.1 was announced in September 2024. The
    post sitemap lists the posts; one titled "<Product> Update v<version>" gives that
    release its `article:published_time`. Artemis 1.2.0, Murmux 1.1 and Typhon 4.2.1 have
    one. "NYMPHES V2 Firmware Update" names V2, not the V2.1 on offer, so it dates nothing.
    """

    manufacturer_name = "Dreadbox"
    manufacturer_slug = "dreadbox"
    manufacturer_website = "https://dreadbox-fx.com"

    SUPPORT_URL = "https://dreadbox-fx.com/support/"
    POST_SITEMAP = "https://dreadbox-fx.com/post-sitemap.xml"

    FIRMWARE_LABEL = re.compile(r"firmware|updater", re.I)
    LABEL_VERSION = re.compile(r"\b(?:v\s*)?(\d+(?:\.\d+)+)\b", re.I)
    FILE_VERSION = re.compile(r"[Vv](\d+)[._](\d+)(?:[._](\d+))?")
    POST_LINK = re.compile(r"https://dreadbox-fx\.com/[a-z0-9-]*(?:update|firmware)[a-z0-9-]*/")
    POST_TITLE = re.compile(r"^(?P<product>.+?)\s+Update\s+v(?P<version>\d+(?:\.\d+)+)$", re.I)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._catalogue: Optional[Dict[str, List[ScrapedFirmware]]] = None

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(part) for part in re.findall(r"\d+", version)) or (0,)

    def _version(self, label: str, href: str) -> Optional[str]:
        match = self.LABEL_VERSION.search(label)
        if match:
            return match.group(1)
        found = self.FILE_VERSION.search(href.rsplit("/", 1)[-1])
        if found:
            return ".".join(part for part in found.groups() if part is not None)
        return None

    def _parse_support(self, html: str) -> Dict[str, List[str]]:
        """Product name -> firmware versions offered, from each download's nearest row."""
        soup = self.parse_html(html)
        products: Dict[str, List[str]] = {}
        for box in soup.select("div.icon-box"):
            label = box.find("h3")
            link = box.find("a", href=True)
            if not label or not link or not self.FIRMWARE_LABEL.search(label.get_text(" ", strip=True)):
                continue
            row = box.find_parent("div", class_="row-inner")
            column = row.find("div", class_="wpb_column") if row else None
            name_heading = column.find("h3") if column else None
            if not name_heading:
                continue
            version = self._version(label.get_text(" ", strip=True), link["href"])
            if not version:
                continue
            name = name_heading.get_text(" ", strip=True)
            versions = products.setdefault(name, [])
            if version not in versions:
                versions.append(version)
        return products

    def _post_release(self, html: str) -> Optional[Tuple[str, str, datetime]]:
        """(product, version, published) from an update post, if its title names both."""
        soup = self.parse_html(html)
        heading = soup.find("h1")
        meta = soup.find("meta", attrs={"property": "article:published_time"})
        if not heading or not meta or not meta.get("content"):
            return None
        match = self.POST_TITLE.match(" ".join(heading.get_text(" ", strip=True).split()))
        if not match:
            return None
        try:
            published = datetime.strptime(meta["content"][:10], "%Y-%m-%d")
        except ValueError:
            return None
        return match.group("product").lower(), match.group("version"), published

    async def _load(self) -> Optional[Dict[str, List[ScrapedFirmware]]]:
        if self._catalogue is not None:
            return self._catalogue

        support = await self.fetch_page_js(self.SUPPORT_URL, wait_for_timeout=10000)
        products = self._parse_support(support) if support else {}
        if not products:
            return None

        dates: Dict[Tuple[str, str], datetime] = {}
        sitemap = await self.fetch_page_js(self.POST_SITEMAP, wait_for_timeout=3000)
        if sitemap is None:
            # Without the sitemap every release would lose its date without a word.
            return None
        for url in dict.fromkeys(self.POST_LINK.findall(sitemap)):
            post = await self.fetch_page_js(url, wait_for_timeout=10000)
            if post is None:
                return None
            release = self._post_release(post)
            if release:
                dates[(release[0], release[1])] = release[2]

        catalogue: Dict[str, List[ScrapedFirmware]] = {}
        for name, versions in products.items():
            releases = []
            for version in versions:
                published = next(
                    (when for (product, posted), when in dates.items()
                     if posted == version and name.lower().startswith(product)),
                    None,
                )
                releases.append(ScrapedFirmware(version=version, release_date=published))
            catalogue[name] = sorted(releases, key=lambda fw: self._version_key(fw.version), reverse=True)

        self._catalogue = catalogue
        return catalogue

    async def fetch_device_list(self) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(success=False, error=f"Could not read Dreadbox's firmware downloads from {self.SUPPORT_URL}")
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    # Every product with firmware is one of the synthesizers; the
                    # effects pedals are analogue.
                    name=name,
                    category="synthesizer",
                    firmware_page_url=self.SUPPORT_URL,
                    product_url=self.SUPPORT_URL,
                )
                for name in catalogue
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(success=False, error=f"Could not read Dreadbox's firmware downloads from {self.SUPPORT_URL}")
        versions = catalogue.get(device_name)
        if versions is None:
            return ScraperResult(success=False, error=f"{device_name} has no firmware download on {self.SUPPORT_URL}")
        return ScraperResult(success=True, firmware_versions=versions)
