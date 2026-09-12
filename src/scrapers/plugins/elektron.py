import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class ElektronScraper(BaseScraper):
    """Elektron instruments, read from their per-product support pages.

    The previous version of this scraper fetched
    `/support/?connection=<product>` and reported the same two versions --
    1.4.0 and 1.55B -- for all eleven products it tracked. That query parameter
    selects nothing: the URL returns a byte-identical 1,785-character page for
    Digitakt, for Syntakt, and for a product name invented to test it. The two
    versions came from news blurbs on that shared page, "OS 1.4.0 for Tonverk" and
    "OS 1.55B for Analog Four MKII", so of twenty-two stored rows exactly one was
    right, and the scrape reported no failures the whole time.

    The real pages live at `/support-downloads/<slug>` and are discovered from the
    support index rather than transcribed, so a slug Elektron changes cannot leave a
    stale list behind. Each update is a `div.group-content` holding the version, the
    date and the changelog:

        <h3>Digitakt OS 1.53</h3>
        <h3>Sep 9, 2026</h3>
        <div class="rich-text"><p>Adds Outbox 8 configuration support...</p>
                               <a href="../wp-content/...OS1.53_dist.zip">DOWNLOAD OS</a>

    The same page also lists companion software under its own heading -- "Elektron
    Transfer 1.10.4" -- which is not the instrument's OS. Requiring "OS" in the
    heading separates them, the way Eventide's H90 page needs its companion apps
    separated from the pedal.
    """

    manufacturer_name = "Elektron"
    manufacturer_slug = "elektron"
    manufacturer_website = "https://www.elektron.se"

    SUPPORT_URL = "https://www.elektron.se/support-downloads"

    # Entries on the support index that are not instruments.
    NOT_A_DEVICE = {
        "accessories", "sound-packs", "overbridge", "transfer", "support-downloads",
    }

    # "Digitakt OS 1.53", "Octatrack MKII OS 1.40C"
    OS_HEADING = re.compile(r"\bOS\s+(\d+(?:\.\d+)+[A-Za-z]?)\s*$")

    # "Sep 9, 2026" on most pages and "Sept 9, 2026" on others. The month is captured
    # and mapped by its first three letters rather than handed to strptime, which
    # accepts "Sep" and rejects "Sept" -- a pattern looser than its parser silently
    # dropped the date on every MKII page.
    DATE_HEADING = re.compile(
        r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2}),\s+(\d{4})$"
    )
    MONTHS = {m: i for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._products: Optional[List[Tuple[str, str]]] = None

    async def _discover_products(self) -> Optional[List[Tuple[str, str]]]:
        """Return (name, page URL) for each instrument on the support index."""
        if self._products is not None:
            return self._products

        html = await self.fetch_page_js(self.SUPPORT_URL, wait_for_timeout=25000)
        if not html:
            return None

        soup = self.parse_html(html)
        found: Dict[str, str] = {}

        for anchor in soup.select('a[href*="/support-downloads/"]'):
            href = anchor["href"]
            slug = href.rstrip("/").split("/")[-1].split("#")[0]
            name = anchor.get_text(" ", strip=True)
            if not slug or slug in self.NOT_A_DEVICE or not name:
                continue
            # The index links each product twice, in the nav and the body.
            found.setdefault(name, f"{self.SUPPORT_URL}/{slug}")

        self._products = sorted(found.items())
        return self._products

    async def fetch_device_list(self) -> ScraperResult:
        products = await self._discover_products()
        if products is None:
            return ScraperResult(
                success=False, error="Could not fetch the Elektron support index"
            )
        if not products:
            return ScraperResult(
                success=False, error="Elektron support index listed no products"
            )

        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category="synthesizer",
                    firmware_page_url=url,
                    product_url=url,
                )
                for name, url in products
            ],
        )

    def _parse_updates(self, html: str, page_url: str) -> List[ScrapedFirmware]:
        """Read the Updates blocks, skipping the companion software below them."""
        soup = self.parse_html(html)
        versions: List[ScrapedFirmware] = []
        seen = set()

        for block in soup.select("div.group-content"):
            headings = block.find_all("h3")
            if not headings:
                continue

            match = next(
                (m for m in (self.OS_HEADING.search(h.get_text(" ", strip=True))
                             for h in headings) if m),
                None,
            )
            if not match:
                continue  # companion software, or a block with no version

            version = match.group(1)
            if version in seen:
                continue
            seen.add(version)

            release_date = None
            for heading in headings:
                dated = self.DATE_HEADING.match(heading.get_text(" ", strip=True))
                if dated:
                    month, day, year = dated.groups()
                    try:
                        release_date = datetime(int(year), self.MONTHS[month], int(day))
                    except (ValueError, KeyError):
                        release_date = None
                    break

            changelog = None
            download_url = None
            rich = block.select_one("div.rich-text")
            if rich:
                paragraph = rich.find("p")
                if paragraph:
                    changelog = paragraph.get_text(" ", strip=True)[:500] or None
                link = rich.find("a", string=re.compile(r"download", re.I))
                if link is None:
                    link = rich.find("a", href=re.compile(r"\.zip$", re.I))
                if link and link.get("href"):
                    # Elektron writes these as "../wp-content/...", so they have to be
                    # resolved against the page or they become the kind of broken join
                    # that reached the database from an older TAL scraper.
                    download_url = urljoin(page_url, link["href"])

            versions.append(
                ScrapedFirmware(
                    version=version,
                    release_date=release_date,
                    download_url=download_url,
                    changelog=changelog,
                )
            )

        return versions

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        html = await self.fetch_page_js(firmware_page_url, wait_for_timeout=25000)
        if not html:
            return ScraperResult(
                success=False, error=f"Failed to fetch {firmware_page_url}"
            )

        versions = self._parse_updates(html, firmware_page_url)
        if not versions:
            # Elektron keeps pages for discontinued instruments that list manuals and
            # no OS. Empty is the honest answer; the fetch itself worked.
            return ScraperResult(success=True, firmware_versions=[])

        return ScraperResult(success=True, firmware_versions=versions)
