import re
import unicodedata
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class EventideScraper(BaseScraper):
    """Eventide plug-ins and software, read from their Docs & Downloads pages.

    One index at /downloads/ lists every product and tags each tile with category
    classes -- `plug-in`, `pedal`, `studio`, `broadcast`, `software`, plus `legacy`
    for discontinued lines. Product pages are the same URL with a `?product=` query,
    and each carries a set of `div.download.card` blocks holding a title, a
    `div.version-number` and collapsed release notes.

    Two things about this vendor decide the whole design.

    **Pedals do not publish a firmware version.** The H90 page's most prominent
    version is 2.2.0, which belongs to Eventide Control, and its next is 1.9.15,
    which is H90 Control -- whose own release notes read "1.9.15 (Requires H90
    firmware 1.9.4+)". The app and the pedal are different products on different
    numbering, and taking either as the pedal's firmware would be wrong. Pedal
    firmware ships through Eventide Device Manager, which fetches it at run time and
    publishes no version anywhere on the site. Checked against H90 and Space, which
    agree. So pedals, rack and broadcast hardware are listed as devices and report no
    version, which renders as "Firmware Unknown".

    **No release dates exist, and these are the places checked.** Recorded because the
    absence looks like an oversight and invites the search to be repeated:

      - Product pages. Release notes are headings with no dates beside them -- zero
        date-shaped strings anywhere in the rendered text of any product page.
      - Stored changelogs. Of 729 Eventide versions held with changelog text and no
        date, one contained a date-shaped string.
      - Installer files. The download links are HTML gates rather than files, so there
        is no Last-Modified to read.
      - Press releases. Thirty of them, none naming a version.
      - The WordPress REST API, which is the one worth warning about. The site exposes
        a `download` post type, and each installer is a post with a `date`. It looks
        exactly like a release date and is not: of 132 installer posts, 80 share
        2025-12-11 and 31 share 2021-08-16, twelve distinct days in total, with the
        two Blackhole installers thirty seconds apart. Those are bulk imports -- the
        guid still points at `web-demo.aws.eventideaudio.com` -- and using them would
        stamp eighty products with one invented release date.

    So `created_at`, the date a scrape first saw a version, is the only date Eventide
    versions carry. The dashboard shows it in its own "Discovered" column, which is
    what it is.

    **Only the pages that carry a version are fetched.** The index is server-side
    filtered -- the unfiltered page contains no download cards at all -- so there is
    no single listing to read, and a product page costs about 350KB. Eventide sends
    no ETag, so revalidation cannot help. Fetching all 125 products daily to read a
    version from roughly half of them is the mistake Focusrite taught: pages that
    carry no version still cost the budget. Only `plug-in` and `software` products
    are fetched, and `legacy` ones are skipped entirely as discontinued.
    """

    manufacturer_name = "Eventide"
    manufacturer_slug = "eventide"
    manufacturer_website = "https://www.eventideaudio.com"

    INDEX_URL = "https://www.eventideaudio.com/downloads/"

    # Category class on the index tile -> this app's device category.
    CATEGORY_MAP = {
        "plug-in": "vst_plugin",
        "software": "other",
        "pedal": "guitar_pedal",
        "studio": "other",
        "broadcast": "other",
    }

    # Categories whose product pages actually carry the product's own version. The
    # rest are listed but never fetched; see the class docstring.
    FETCHED_CATEGORIES = {"plug-in", "software"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Populated by fetch_device_list and read by fetch_firmware_versions, which
        # is only given a name and a URL. The service reuses one instance per run.
        self._categories: Dict[str, str] = {}

    @staticmethod
    def _normalise_name(name: str) -> str:
        """Strip the decoration Eventide puts in product and download titles.

        "Omnipressor®" arrives as "‍Omnipressor Installer (Mac 64-bit)" -- a
        zero-width joiner before the name, which is invisible everywhere except a
        string comparison, and exactly how a scrape silently creates a second row
        beside the one your devices are attached to.
        """
        name = unicodedata.normalize("NFKC", name)
        name = re.sub(r"[​-‏⁠﻿]", "", name)  # zero-width marks
        name = name.replace("®", "").replace("™", "")  # (R) and (TM)
        return re.sub(r"\s+", " ", name).strip()

    async def _load_index(self) -> Optional[List[Tuple[str, str, str]]]:
        """Return (name, category class, product URL) for every non-legacy product."""
        html = await self.fetch_page(self.INDEX_URL)
        if not html:
            return None

        soup = self.parse_html(html)
        products: List[Tuple[str, str, str]] = []
        seen = set()

        for tile in soup.select("div.product"):
            classes = set(tile.get("class", []))
            if "legacy" in classes:
                continue  # discontinued; nothing is published for these any more

            category = next((c for c in self.CATEGORY_MAP if c in classes), None)
            if not category:
                continue

            link = tile.select_one('a[href*="/downloads/?product="]')
            if not link:
                continue

            href = link["href"]
            # The query value is the product's canonical name, and reading it beats
            # the tile text, which appends a marketing tagline to the name.
            raw = unquote(href.split("product=")[1]).replace("+", " ")
            name = self._normalise_name(raw)
            if not name or name in seen:
                continue

            seen.add(name)
            url = href if href.startswith("http") else f"{self.manufacturer_website}{href}"
            products.append((name, category, url))

        return products

    async def fetch_device_list(self) -> ScraperResult:
        products = await self._load_index()
        if products is None:
            return ScraperResult(success=False, error="Could not fetch the Eventide downloads index")
        if not products:
            return ScraperResult(
                success=False,
                error="Eventide downloads index parsed but listed no products",
            )

        self._categories = {name: category for name, category, _url in products}

        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category=self.CATEGORY_MAP[category],
                    firmware_page_url=url,
                    product_url=url,
                    # Pedals, rack and broadcast hardware update through Eventide
                    # Device Manager, which fetches firmware at run time and publishes
                    # no version on the site. The plug-ins and software do publish, so
                    # this is set per category rather than for the whole vendor.
                    firmware_availability=(
                        None if category in self.FETCHED_CATEGORIES else "not_published"
                    ),
                )
                for name, category, url in products
            ],
        )

    @staticmethod
    def _slug(name: str) -> str:
        """Match the slug Eventide puts in a download card's class list."""
        return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

    def _installer_versions(self, html: str, device_name: str) -> List[ScrapedFirmware]:
        """Read versions from the download card that belongs to this product.

        A product page holds several cards and most are not the product. The anchor is
        structural -- every card lists the slugs of the products it applies to as CSS
        classes -- with the title used only to disambiguate between them:

        - The H910 page carries both "H910/H910 Dual Installer" and "PreSonus
          Promotion Installer", and both are tagged h910-harmonizer. Requiring the
          product's first token in the title separates them. Requiring the word
          "Installer" does not, and would drop the many products whose download is
          titled plainly, like "H3000 Band Delays Mk II (Mac 64-bit)".
        - Obliterate's cards have no title element at all. A product with a single
          candidate has nothing to confuse it with.
        - Eventide Device Manager (EDM) is tagged `device-manager`, which is not the
          slug its name produces, so a title match is the fallback when no card
          claims the slug.
        - Bundles like Pro Reverb Bundle list their components' installers, each with
          its own version. No single number describes the bundle, so it reports none
          rather than picking one arbitrarily.

        User guides are excluded by the pipe in their version ("Version 9 | English"),
        which is a manual revision rather than a release.
        """
        soup = self.parse_html(html)
        name = self._normalise_name(device_name)
        slug = self._slug(name)
        # "Eventide Device Manager (EDM)" -> "eventide device manager"
        bare = re.sub(r"\s*\(.*?\)", "", name).strip().lower()
        first_token = bare.split()[0] if bare.split() else ""

        cards = soup.select("div.download.card")
        claiming = [c for c in cards if slug in c.get("class", [])]
        if not claiming:
            claiming = [
                c
                for c in cards
                if (link := c.select_one("a.download-link"))
                and bare and bare in self._normalise_name(link.get_text(" ", strip=True)).lower()
            ]

        named, unnamed = [], []
        for card in claiming:
            version_node = card.select_one("div.version-number")
            if not version_node:
                continue
            raw = version_node.get_text(" ", strip=True)
            if "|" in raw:
                continue  # a documentation revision, not a release
            match = re.search(r"\b(\d+(?:\.\d+)+)\b", raw)
            if not match:
                continue

            link = card.select_one("a.download-link")
            entry = (match.group(1), card.select_one("div.card-body"))
            if link:
                title = self._normalise_name(link.get_text(" ", strip=True)).lower()
                if first_token and first_token in title:
                    named.append(entry)
            else:
                unnamed.append(entry)

        candidates = named or (unnamed if len({v for v, _ in unnamed}) == 1 else [])
        if not candidates:
            return []

        # Platforms can sit on different releases -- H9 Control is 4.1.6 on macOS and
        # 4.0.1 on Windows -- and the app tracks one latest per product, so the newest
        # is taken. It answers "is there something newer than mine", which is the
        # question being asked, at the cost of naming a version one platform lacks.
        version, body = max(candidates, key=lambda e: self._version_key(e[0]))
        return self._history(body, version)

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(p) for p in re.findall(r"\d+", version)) or (0,)

    def _history(self, body, current: str) -> List[ScrapedFirmware]:
        """Build the version list from the release-notes headings, newest first.

        The heading level is not consistent: Blackhole puts an `h2` "Release Notes"
        above `h3` versions, while H90 makes each version an `h2` directly. Reading
        only one level silently returns a single version for half the catalogue, so
        both are scanned.

        Only headings that begin with a bare version count. The notes body also lists
        firmware requirements ("H90: 1.9.4+") and OS requirements ("macOS 10.14"),
        which look like versions and are not -- and a heading like "Release Notes" or
        "Firmware Requirements" is skipped by the same rule.
        """
        versions: List[ScrapedFirmware] = []
        seen = set()

        if body is not None:
            for heading in body.select("h2, h3"):
                text = heading.get_text(" ", strip=True)
                match = re.match(r"^(\d+(?:\.\d+)+)\b", text)
                if not match:
                    continue
                version = match.group(1)
                if version in seen:
                    continue
                seen.add(version)
                notes = heading.find_next_sibling()
                versions.append(
                    ScrapedFirmware(
                        version=version,
                        # Eventide dates none of these, and inventing one would put a
                        # fabricated date in front of the user.
                        release_date=None,
                        changelog=notes.get_text(" ", strip=True)[:500] if notes else None,
                    )
                )

        if current not in seen:
            versions.insert(0, ScrapedFirmware(version=current))
        return versions

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        category = self._categories.get(self._normalise_name(device_name))

        if category is None:
            # Called without fetch_device_list having run, so rebuild the map rather
            # than guessing a category and fetching a page that cannot help.
            products = await self._load_index()
            if products is None:
                return ScraperResult(
                    success=False, error="Could not fetch the Eventide downloads index"
                )
            self._categories = {name: cat for name, cat, _ in products}
            category = self._categories.get(self._normalise_name(device_name))

        if category is None:
            return ScraperResult(
                success=False, error=f"{device_name} is not listed on the Eventide index"
            )

        if category not in self.FETCHED_CATEGORIES:
            # Hardware. Eventide publishes no firmware version for it, so this is a
            # success that reports nothing rather than a failure. See the docstring.
            return ScraperResult(success=True, firmware_versions=[])

        html = await self.fetch_page(firmware_page_url)
        if not html:
            return ScraperResult(
                success=False, error=f"Could not fetch the Eventide page for {device_name}"
            )

        return ScraperResult(success=True, firmware_versions=self._installer_versions(html, device_name))
