import re
from typing import List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScraperResult


class KeithMcMillenScraper(BaseScraper):
    """Keith McMillen Instruments, whose firmware versions are not published.

    This scraper lists the products and reports no version for any of them. That is
    the finding rather than a gap, so the search is written down to save repeating it
    (checked 2026-09-13):

    - **The downloads page publishes editors, not firmware.** Every version on it
      belongs to a companion app -- "K-Board Editor v1.3.0", "BopPad Editor v1.2.0",
      "K-Board Pro 4 Editor v1.4.0" -- or to a manual, or to a Bitwig control script
      ("KMI Control Scripts and MPE Template v1.3"). Reading any of them as the
      instrument's firmware is the trap Eventide's H90 page sets with Eventide
      Control, and KMI sets it about twenty times on one page.
    - **The "Firmware Downloads" heading is not what it sounds like.** It introduces
      SendSysEx, a command-line utility that can push firmware to a device. The
      utility is versioned; the firmware it pushes is not.
    - **The Zendesk help centre carries no release notes.** Six articles match a
      firmware search and all are how-to guides -- "Legacy Users: Updating SoftStep
      Firmware" and similar. The version-shaped strings in them are macOS versions
      and editor versions in prose.
    - **One change log exists**, a PDF for the K-Board Pro 4, for one product.

    So firmware ships inside the Editor applications, the way Focusrite's ships
    inside Focusrite Control, and no number is published anywhere to compare against.
    The products are listed with `firmware_availability="not_published"` so the
    catalogue says why rather than showing an unexplained blank, and their pages stay
    reachable for a manual check.

    Products are read from the "<name> Downloads" headings rather than transcribed,
    so a product KMI adds appears without an edit here.
    """

    manufacturer_name = "Keith McMillen Instruments"
    manufacturer_slug = "keithmcmillen"
    manufacturer_website = "https://www.keithmcmillen.com"

    DOWNLOADS_URL = "https://www.keithmcmillen.com/downloads/"

    # "K-Board Downloads", "12 Step Downloads".
    PRODUCT_HEADING = re.compile(r"^(.+?)\s+Downloads$", re.I)

    # "Firmware Downloads" matches the pattern above and is a section for SendSysEx,
    # a utility, rather than a product.
    NOT_A_PRODUCT = {"firmware"}

    # K-Mix is an audio interface; everything else KMI makes is a controller.
    AUDIO_INTERFACES = {"k-mix"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._products: Optional[List[str]] = None

    def _category_for(self, name: str) -> str:
        return "audio_interface" if name.lower() in self.AUDIO_INTERFACES else "midi_controller"

    def _parse_products(self, html: str) -> List[str]:
        soup = self.parse_html(html)
        found: List[str] = []
        for heading in soup.select("h2, h3"):
            matched = self.PRODUCT_HEADING.match(heading.get_text(" ", strip=True))
            if not matched:
                continue
            name = " ".join(matched.group(1).split())
            if name.lower() in self.NOT_A_PRODUCT or name in found:
                continue
            found.append(name)
        return found

    async def _load(self) -> Optional[List[str]]:
        if self._products is not None:
            return self._products
        html = await self.fetch_page(self.DOWNLOADS_URL)
        if not html:
            return None
        products = self._parse_products(html)
        if not products:
            return None
        self._products = products
        return products

    async def fetch_device_list(self) -> ScraperResult:
        products = await self._load()
        if products is None:
            return ScraperResult(
                success=False, error=f"Failed to read {self.DOWNLOADS_URL}"
            )

        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category=self._category_for(name),
                    firmware_page_url=self.DOWNLOADS_URL,
                    product_url=self.DOWNLOADS_URL,
                    # Recorded so the catalogue reads "not published" rather than a
                    # bare em-dash, which would look like a scraper that had stopped
                    # working. See the class docstring for what was checked.
                    firmware_availability="not_published",
                )
                for name in sorted(products)
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        """Succeed while reporting nothing, because nothing is what KMI publishes.

        Success rather than failure: the page loaded and the product simply has no
        discoverable version. Reporting a failure would raise a false alarm on every
        run forever.
        """
        return ScraperResult(success=True, firmware_versions=[])
