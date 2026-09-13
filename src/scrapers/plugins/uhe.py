import logging
import re
import unicodedata
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)

MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]
DATE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{1,2}),\s+(\d{4})"
)


class UHeScraper(BaseScraper):
    """u-he, whose site is halfway through moving its products to a new section.

    Products are discovered from the links on `/products/`, and there are three kinds
    of link, which have to be told apart rather than assumed:

    - **Older products** live at `/products/<slug>/` with a `releasenotes.html` beside
      them: one `div.releasenote` per release, each holding its own date and heading --

          <div class="rn-date"> August 27, 2024 </div>
          <h3>Diva 1.4.8 (revision 16519)</h3>

      Every entry is dated, so the whole history arrives with dates. The date sits
      *before* the heading, which is why pairing by reading onward from the heading
      found none.

    - **Newer products** live under `/products/plug-ins/<slug>/`, with a `releases/`
      page instead: a heading per version, then "published | Wednesday, July 15,
      2026 | revision | 22175". Zebra 3 and Zebralette 3 are there so far.

    - **Redirect stubs.** `/products/zebra3/` and `/products/synths/zebra3/` are both
      a page whose title is a URL and whose `rel=canonical` names the real product.
      They are followed, and a product reached twice is listed once. The legacy
      Zebralette at `/products/zebralette/` is a different product from Zebralette 3,
      which the freeware link redirects to.

    **The release notes exclude the latest builds** -- the page says so -- so the
    installers linked from `/products/` are checked against them. On 2026-09-13 all
    eighteen agreed. An installer newer than the notes is added as the latest version,
    undated. They are matched on the product's URL slug, not its name: the notes say
    "Hive 2" and "Uhbik 2" where the installers say `Hive_` and `Uhbik_`, and a
    name-keyed match silently found nothing for either. Installer names are also
    irregular: `Zebra_Legacy_294_16765_Mac.zip`,
    `TyrellN6_300_public_beta_16976_Mac.zip`, `Zebralette3_300_20399__Win.zip`, and
    lowercase duplicates of some.

    **TyrellN6's current release is a public beta** -- it is the only build offered,
    and its release notes list it -- so it is recorded. "Beta" is dropped from the
    name, since it describes the release rather than the product.

    **Four products are Eurorack modules, and three publish no firmware version.**
    CVilization has dated release notes. Wiretap, MELT and CEN2RION have an empty
    release notes page, no installer and no release archive link (checked
    2026-09-13); they are listed as not published rather than left blank.
    """

    manufacturer_name = "u-he"
    manufacturer_slug = "uhe"
    manufacturer_website = "https://u-he.com"

    INDEX_URL = "https://u-he.com/products/"

    # "/products/diva/", "/products/synths/zebra3", "https://u-he.com/products/x/"
    PRODUCT_LINK = re.compile(r"^(?:https://u-he\.com)?(/products/(?:[a-z-]+/)?([a-z0-9-]+))/?$")
    NOT_PRODUCTS = {"soundsets", "synths", "effects", "bundles", "eurorack", "freeware", "plug-ins"}
    # "Diva 1.4.8 (revision 16519)", "Triple Cheese 1.3 (revision 12092)"
    NOTE_HEADING = re.compile(r"^(.+?)\s+(\d+(?:\.\d+)+)\s*(?:\((?:revision|rev\.?)\s*\d+\))?\s*$", re.I)
    # "anchor 3.0.2" -- the anchor icon's text comes first.
    RELEASE_HEADING = re.compile(r"(\d+(?:\.\d+)+)\s*$")
    PUBLISHED = re.compile(r"published\s+(?:[A-Za-z]+,\s+)?" + DATE.pattern)
    # "Diva_148_16519_Mac", "Zebra_Legacy_294_...", "TyrellN6_300_public_beta_16976_...",
    # "Zebralette3_300_20399__Win".
    INSTALLER = re.compile(
        r"dl\.u-he\.com/releases/([A-Za-z0-9_]+?)_(\d{1,4})_(?:[a-z_]+?_)?\d+_+(?:Mac|Win|Linux)",
        re.I,
    )
    EURORACK = {"cvilization", "wiretap", "melt", "cen2rion"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # name -> (url, category, versions)
        self._catalogue: Optional[Dict[str, Tuple[str, str, List[ScrapedFirmware]]]] = None

    @staticmethod
    def _key(name: str) -> str:
        """Twangström, Zebra_Legacy and Zebra Legacy all reduce to the same key."""
        plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
        return re.sub(r"[^a-z0-9]", "", plain.lower())

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(part) for part in version.split("."))

    @staticmethod
    def _date(text: str) -> Optional[datetime]:
        matched = DATE.search(text or "")
        if not matched:
            return None
        month, day, year = matched.groups()
        try:
            return datetime(int(year), MONTHS.index(month.lower()) + 1, int(day))
        except ValueError:
            return None

    @staticmethod
    def _clean_name(name: str) -> str:
        return re.sub(r"\s+Beta$", "", name.strip())

    def _installer_versions(self, soup) -> Dict[str, Set[str]]:
        found: Dict[str, Set[str]] = {}
        for anchor in soup.find_all("a", href=True):
            matched = self.INSTALLER.search(anchor["href"])
            if matched:
                name, digits = matched.groups()
                found.setdefault(self._key(name), set()).add(".".join(digits))
        return found

    def _parse_notes(self, html: str) -> Tuple[Optional[str], List[ScrapedFirmware]]:
        soup = self.parse_html(html)
        title = None
        for heading in soup.find_all(["h1", "h2"]):
            text = heading.get_text(" ", strip=True)
            if text.startswith("Release notes:"):
                title = self._clean_name(text.split(":", 1)[1])
                break
        versions: List[ScrapedFirmware] = []
        seen: Set[str] = set()
        for note in soup.select("div.releasenote"):
            heading = note.find(["h2", "h3", "h4"])
            matched = self.NOTE_HEADING.match(heading.get_text(" ", strip=True)) if heading else None
            if not matched or matched.group(2) in seen:
                continue
            seen.add(matched.group(2))
            dated = note.select_one(".rn-date")
            versions.append(ScrapedFirmware(
                version=matched.group(2),
                release_date=self._date(dated.get_text(" ", strip=True)) if dated else None,
            ))
        return title, versions

    def _parse_releases(self, html: str) -> List[ScrapedFirmware]:
        soup = self.parse_html(html)
        versions: List[ScrapedFirmware] = []
        seen: Set[str] = set()
        for heading in soup.find_all("h2"):
            matched = self.RELEASE_HEADING.search(heading.get_text(" ", strip=True))
            if not matched or matched.group(1) in seen:
                continue
            seen.add(matched.group(1))
            chunk = []
            for node in heading.next_elements:
                if getattr(node, "name", None) == "h2" and node is not heading:
                    break
                if isinstance(node, str):
                    chunk.append(node)
            published = self.PUBLISHED.search(" ".join(" ".join(chunk).split()))
            versions.append(ScrapedFirmware(
                version=matched.group(1),
                release_date=self._date(published.group(0)) if published else None,
            ))
        return versions

    @staticmethod
    def _canonical(html: str, soup) -> Optional[str]:
        link = soup.find("link", rel="canonical")
        return link["href"] if link and link.get("href") else None

    def _page_name(self, soup) -> Optional[str]:
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        if not title or title.startswith("http"):
            return None
        return self._clean_name(title.split(" | ")[0].split(":")[0])

    async def _resolve(
        self, url: str, visited: Set[str]
    ) -> Optional[Tuple[str, str, List[ScrapedFirmware]]]:
        """(name, product url, versions) for one index link, or None for a duplicate."""
        if "/products/plug-ins/" not in url:
            notes = await self.fetch_page(url + "releasenotes.html")
            title, versions = self._parse_notes(notes) if notes else (None, [])
            if versions:
                return title, url, versions
        else:
            title = None

        page = await self.fetch_page(url)
        soup = self.parse_html(page) if page else None
        target = (self._canonical(page, soup) if soup else None) or url
        target = target if target.endswith("/") else target + "/"

        if "/products/plug-ins/" in target:
            if target in visited:
                return None
            visited.add(target)
            releases = await self.fetch_page(target + "releases/")
            product = page if target == url else await self.fetch_page(target)
            name = self._page_name(self.parse_html(product)) if product else None
            return name, target, (self._parse_releases(releases) if releases else [])

        name = title or (self._page_name(soup) if soup else None)
        return name, url, []

    async def _load(self) -> Optional[Dict[str, Tuple[str, str, List[ScrapedFirmware]]]]:
        if self._catalogue is not None:
            return self._catalogue

        index = await self.fetch_page(self.INDEX_URL)
        if not index:
            return None
        soup = self.parse_html(index)
        installers = self._installer_versions(soup)

        urls: List[Tuple[str, str]] = []
        for anchor in soup.find_all("a", href=True):
            matched = self.PRODUCT_LINK.match(anchor["href"])
            if not matched or matched.group(2) in self.NOT_PRODUCTS:
                continue
            url = f"{self.manufacturer_website}{matched.group(1)}/"
            if url not in (u for u, _ in urls):
                urls.append((url, matched.group(2)))
        if not urls:
            return None

        catalogue: Dict[str, Tuple[str, str, List[ScrapedFirmware]]] = {}
        visited: Set[str] = set()
        for url, slug in urls:
            resolved = await self._resolve(url, visited)
            if resolved is None or not resolved[0]:
                continue
            name, product_url, versions = resolved
            if name in catalogue:
                continue

            # Keyed on the URL slug first: the notes call it "Hive 2" and the installer
            # is "Hive_212_...", so display names do not match across the two.
            slug_key = self._key(product_url.rstrip("/").rsplit("/", 1)[-1])
            offered = installers.get(slug_key) or installers.get(self._key(name), set())
            known = {fw.version for fw in versions}
            newer = [v for v in offered if v not in known
                     and (not versions or self._version_key(v) > max(self._version_key(k) for k in known))]
            if newer:
                latest = max(newer, key=self._version_key)
                logger.info("u-he %s: installer %s is newer than the release notes", name, latest)
                versions = [ScrapedFirmware(version=latest)] + versions

            versions.sort(key=lambda fw: self._version_key(fw.version), reverse=True)
            category = "synthesizer" if slug in self.EURORACK else "vst_plugin"
            catalogue[name] = (product_url, category, versions)

        if not catalogue:
            return None
        self._catalogue = catalogue
        return catalogue

    async def fetch_device_list(self) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(success=False, error=f"No products found at {self.INDEX_URL}")
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category=category,
                    firmware_page_url=url,
                    product_url=url,
                    # No release notes, installer or archive: see the class docstring.
                    firmware_availability=None if versions else "not_published",
                )
                for name, (url, category, versions) in sorted(catalogue.items())
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        catalogue = await self._load()
        if catalogue is None:
            return ScraperResult(success=False, error=f"No products found at {self.INDEX_URL}")
        entry = catalogue.get(device_name)
        return ScraperResult(success=True, firmware_versions=list(entry[2]) if entry else [])
