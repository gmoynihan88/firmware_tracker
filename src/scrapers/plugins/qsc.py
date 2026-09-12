import re
from datetime import datetime
from typing import Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class QSCScraper(BaseScraper):
    """Scraper for QSC powered speakers and audio equipment."""

    manufacturer_name = "QSC"
    manufacturer_slug = "qsc"
    manufacturer_website = "https://www.qscaudio.com"

    # QSC moved firmware off /support/software-firmware/, which now 404s, to
    # /resources/software-and-firmware/. Only some product lines have firmware at
    # all; the CP, KS and KLA products appear on the index as catalogue entries,
    # not as downloads.
    K2_FIRMWARE_URL = "https://www.qscaudio.com/resources/software-and-firmware/k2-firmware/"
    TOUCHMIX_FIRMWARE_URL = "https://www.qscaudio.com/resources/software-and-firmware/touchmix/"

    # Products QSC publishes no firmware for. Reported as an empty success so the
    # absence is a recorded fact rather than a fetch that quietly failed.
    NO_FIRMWARE_PUBLISHED = {"KS212C", "KS118", "CP12", "CP8", "KLA12"}

    # "Firmware version for all models: version 2.1.43" -- the K.2 line ships one
    # build across K8.2, K10.2 and K12.2.
    K2_VERSION = re.compile(
        r"Firmware\s+version\s+for\s+all\s+models:\s*version\s*(\d+(?:\.\d+)+)", re.I
    )

    # "Version 2.1 – 8/11/2025" on the K.2 page. Anchored to the version it follows
    # rather than taking the first date on the page, because the page also carries
    # dates that belong to documents. Read as US month/day: QSC is a US company, and
    # the value it produces for 8/11/2025 matches what the page's own listing shows.
    K2_RELEASE_DATE = re.compile(
        r"Version\s+\d+(?:\.\d+)*\s*[\u2013\u2014-]\s*(\d{1,2}/\d{1,2}/\d{4})"
    )

    # "Recommended TouchMix-8/-16 Firmware: 3.0.0955"
    TOUCHMIX_VERSION = re.compile(
        r"Recommended\s+(?P<models>TouchMix[-\w/\s]*?)\s+Firmware:\s*(?P<version>\d+(?:\.\d+)+)",
        re.I,
    )

    KNOWN_PRODUCTS = [
        ("K12.2", "audio_interface", K2_FIRMWARE_URL),
        ("K10.2", "audio_interface", K2_FIRMWARE_URL),
        ("K8.2", "audio_interface", K2_FIRMWARE_URL),
        ("TouchMix-30 Pro", "audio_interface", TOUCHMIX_FIRMWARE_URL),
        ("TouchMix-16", "audio_interface", TOUCHMIX_FIRMWARE_URL),
        ("TouchMix-8", "audio_interface", TOUCHMIX_FIRMWARE_URL),
        ("KS212C", "audio_interface", "https://www.qscaudio.com/resources/software-and-firmware/"),
        ("KS118", "audio_interface", "https://www.qscaudio.com/resources/software-and-firmware/"),
        ("CP12", "audio_interface", "https://www.qscaudio.com/resources/software-and-firmware/"),
        ("CP8", "audio_interface", "https://www.qscaudio.com/resources/software-and-firmware/"),
        ("KLA12", "audio_interface", "https://www.qscaudio.com/resources/software-and-firmware/"),
    ]

    async def fetch_device_list(self) -> ScraperResult:
        """Return the list of known QSC products."""
        devices = [
            ScrapedDevice(
                name=name,
                category=category,
                firmware_page_url=url,
                product_url=f"https://www.qsc.com/products-solutions/loudspeakers/{name.lower().replace(' ', '-').replace('.', '')}/",
            )
            for name, category, url in self.KNOWN_PRODUCTS
        ]
        return ScraperResult(success=True, devices=devices)

    def _touchmix_version_for(self, device_name: str, text: str) -> Optional[str]:
        """Match a TouchMix model to its recommended firmware line.

        The page groups models: "TouchMix-8/-16" share a build while the -30 Pro
        has its own, so the model suffix has to be matched rather than the family.
        """
        suffix = device_name.replace("TouchMix", "").strip().lstrip("-").lower()
        for match in self.TOUCHMIX_VERSION.finditer(text):
            models = match.group("models").lower()
            # "touchmix-8/-16" -> {"8", "16"}; "touchmix-30 pro" -> {"30 pro"}
            listed = {
                part.strip().lstrip("-")
                for part in models.replace("touchmix", "").split("/")
                if part.strip().strip("-")
            }
            if suffix in listed:
                return match.group("version")
        return None

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        """Fetch the current firmware version for a QSC product."""
        if device_name in self.NO_FIRMWARE_PUBLISHED:
            # Verified against the firmware index: these appear only as catalogue
            # entries. Empty is the correct answer, not a failure.
            return ScraperResult(success=True, firmware_versions=[])

        html = await self.fetch_page_js(firmware_page_url, wait_for_timeout=25000)
        if not html:
            return ScraperResult(
                success=False, error=f"Failed to fetch {firmware_page_url}"
            )

        text = re.sub(r"\s+", " ", self.parse_html(html).get_text(" "))

        release_date = None

        if device_name.startswith("TouchMix"):
            version = self._touchmix_version_for(device_name, text)
            # No date is read for TouchMix. The only dates on that page are "Revised
            # 06/07/2017" stamps on the installation instructions, so using them would
            # date firmware 3.0.0955 to 2017.
        else:
            match = self.K2_VERSION.search(text)
            version = match.group(1) if match else None
            release_date = self._k2_release_date(text)

        if not version:
            return ScraperResult(
                success=False,
                error=f"No firmware version found for {device_name} on {firmware_page_url}",
            )

        return ScraperResult(
            success=True,
            firmware_versions=[
                ScrapedFirmware(
                    version=version,
                    release_date=release_date,
                    download_url=firmware_page_url,
                )
            ],
        )

    def _k2_release_date(self, text: str) -> Optional[datetime]:
        """Read the K.2 release date, which the page prints beside the version.

        This existed already, in a `_parse_k2_firmware_page` that nothing called --
        so the date reached the database once, before the live path was rewritten
        without it, and could not be produced again. The stored value survived only
        because a rescrape does not overwrite a date with nothing. A fresh deployment
        would have lost it.
        """
        match = self.K2_RELEASE_DATE.search(text)
        if not match:
            return None
        try:
            return datetime.strptime(match.group(1), "%m/%d/%Y")
        except ValueError:
            return None
