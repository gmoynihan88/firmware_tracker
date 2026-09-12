import json
import re
from datetime import datetime
from typing import Dict, List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class PetersonScraper(BaseScraper):
    """Peterson strobe tuners, read from the firmware history on their support page.

    The previous version pointed at product pages on the shop, which carry prices and
    no firmware at all. What it stored as versions were **manual revisions** picked up
    from elsewhere on the site -- "StroboStomp HD English v1.1", "StroboStomp LE
    English v1.1" -- which is why four of six products reported 1.1. That is the
    "User Guide V4" false positive, and it survived because the numbers look exactly
    like firmware.

    The real source is one page. `/support/` has a Firmware History section whose
    entries each carry a `data-update` attribute holding JSON:

        {"product": "StroboPLUS HD", "versionString": "1.1.12",
         "dateCreated": "May, 04 2017 15:01:00",
         "features": [{"feature": "Various bug fixes...", "public": 1},
                      {"feature": "not for public consumption", "public": 0}]}

    So one fetch covers the whole range with exact dates and changelogs, and no
    pattern has to guess which numbers on a page are releases.

    Peterson writes StroboPLUS where the database has StroboPlus, so products are
    matched case-insensitively. Getting that wrong creates a second row and orphans
    the one a user's devices are attached to.
    """

    manufacturer_name = "Peterson"
    manufacturer_slug = "peterson"
    manufacturer_website = "https://www.petersontuners.com"

    SUPPORT_URL = "https://www.petersontuners.com/support/"

    # The first six were already tracked. The rest appear in the firmware history and
    # were not, so they were being missed entirely. StroboRack and Body Beat Sync stay
    # even though the history does not list them: they are real products, and dropping
    # them would orphan their rows.
    KNOWN_PRODUCTS = [
        ("StroboStomp Mini", "guitar_pedal", SUPPORT_URL),
        ("StroboStomp HD", "guitar_pedal", SUPPORT_URL),
        ("StroboPlus HD", "guitar_pedal", SUPPORT_URL),
        ("StroboClip HD", "guitar_pedal", SUPPORT_URL),
        ("StroboRack", "guitar_pedal", SUPPORT_URL),
        ("Body Beat Sync", "guitar_pedal", SUPPORT_URL),
        ("StroboStomp LE", "guitar_pedal", SUPPORT_URL),
        ("StroboClip HDC", "guitar_pedal", SUPPORT_URL),
        ("StroboPLUS HDC", "guitar_pedal", SUPPORT_URL),
        ("StroboVUE", "other", SUPPORT_URL),
        ("Stomp Classic", "guitar_pedal", SUPPORT_URL),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The whole range comes from one page, so it is fetched once per run.
        self._history: Optional[Dict[str, List[ScrapedFirmware]]] = None

    async def fetch_device_list(self) -> ScraperResult:
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category=category,
                    firmware_page_url=url,
                    product_url=url,
                )
                for name, category, url in self.KNOWN_PRODUCTS
            ],
        )

    def _parse_history(self, html: str) -> Dict[str, List[ScrapedFirmware]]:
        """Read every firmware entry, keyed by lowercased product name."""
        soup = self.parse_html(html)
        history: Dict[str, List[ScrapedFirmware]] = {}

        for entry in soup.select("div.firmwareEntry"):
            raw = entry.get("data-update")
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except ValueError:
                continue

            product = (data.get("product") or "").strip()
            version = (data.get("versionString") or "").strip()
            if not product or not version:
                continue

            release_date = None
            created = data.get("dateCreated")
            if created:
                try:
                    release_date = datetime.strptime(created, "%B, %d %Y %H:%M:%S")
                except ValueError:
                    release_date = None

            # Entries carry unreleased notes alongside the published ones, flagged
            # public 0. Those are Peterson's internal record, not a changelog.
            notes = [
                f.get("feature", "").strip()
                for f in data.get("features") or []
                if f.get("public") and f.get("feature")
            ]

            history.setdefault(product.lower(), []).append(
                ScrapedFirmware(
                    version=version,
                    release_date=release_date,
                    changelog=" ".join(notes)[:500] or None,
                )
            )

        return history

    @staticmethod
    def _version_key(version: str) -> tuple:
        return tuple(int(p) for p in re.findall(r"\d+", version)) or (0,)

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        if self._history is None:
            html = await self.fetch_page(self.SUPPORT_URL)
            if not html:
                return ScraperResult(
                    success=False, error=f"Failed to fetch {self.SUPPORT_URL}"
                )
            self._history = self._parse_history(html)

        versions = self._history.get(device_name.lower())
        if not versions:
            # Peterson sells tuners that take no firmware at all, and the history
            # simply does not list them. The page loaded, so this is an absence.
            return ScraperResult(success=True, firmware_versions=[])

        return ScraperResult(
            success=True,
            firmware_versions=sorted(
                versions, key=lambda fw: self._version_key(fw.version), reverse=True
            ),
        )
