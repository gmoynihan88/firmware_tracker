import json
import re
from datetime import datetime
from typing import Dict, List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class UniversalAudioScraper(BaseScraper):
    """Universal Audio: UAFX pedals and the OX, which publish dated firmware, and
    UADX plugins, which publish no version at all.

    Splitting those two is the point of this file. An earlier version treated the
    whole vendor as unpublishable and reported nothing for anything, which was right
    about the plugins and wrong about the hardware.

    **UAFX pedals and the OX are fully published**, in Zendesk articles that the Help
    Center API returns as HTML:

        UAFX Firmware Release Notes    <h2>UAFX Version 2.0.2</h2>
                                       <h4>December 22, 2025</h4>
        OX Amp Top Box Release Notes   <h4>OX Firmware v1.2 — November 12, 2019</h4>

    Sixteen UAFX versions back to March 2021 and three OX versions back to January
    2018, every one dated. The two articles are shaped differently -- UAFX puts the
    date in the heading after the version, the OX puts both in one heading -- so they
    get one parser each rather than a pattern loose enough for both.

    The OX article also contains `<h2>How To Install OX Firmware v1.2</h2>`, which is
    an instruction rather than a release. Requiring a date in the same heading is what
    excludes it; a version-only pattern would record the install guide as a release
    every time the article was edited.

    **UAFX firmware is one train across the range.** UA versions the platform, not
    each pedal -- "UAFX Version 2.0.0 / All UAFX pedals with two footswitches" -- so
    all 21 pedals report the same list, the way Roland's System Program 1.82 covers
    MC-101, MC-707 and VERSELAB MV-1. `scripts/audit_scrapers.py` flags one version
    shared across most of a vendor's catalogue, and for this vendor that finding is
    expected rather than the Elektron bug it is designed to catch.

    Pedals are discovered from the shop's Shopify collection endpoint rather than
    listed here, and the `category guitar:UAFX Pedals` tag is what separates the 21
    pedals from the OX beside them in the same collection.

    **The UADX plugins publish nothing**, and that is a finding rather than a gap
    waiting to be filled, so the search is written down to save repeating it
    (checked 2026-09-10, re-checked 2026-09-12):

    - `help.uaudio.com` runs Zendesk and its Help Center API answers fine. There is a
      "UAD Native Plug-Ins Release Notes" article, which sounds exactly right and is
      not. It groups changes by month, names the plugins that changed, and gives no
      version numbers at all -- the only version-shaped strings in it are DAW versions
      like "Pro Tools 2025.6". Two of the ten products here are mentioned; the rest
      never appear.
    - UA Connect fetches `external-content.db` from S3, which would be the manifest.
      It is an encrypted blob.
    - `plugins.uaudio.com` returns 403 for everything, including a slug made up to
      test it, so its refusal says nothing about what exists.
    - Every `uaudio.com` release-notes path 404s, confirmed against a control URL that
      returned byte-identical content.

    The previous version of this file carried a `KNOWN_FIRMWARE` table, and the
    problem with it was worse than going stale. Its ten entries matched the versions
    installed on the developer's own machine exactly, because that is where they came
    from. So it reported every UA plugin as up to date by construction, could never
    report anything else, and paired each version with an invented release date. The
    app's whole purpose is to say when an update is waiting; for these plugins it
    cannot, and saying so is more useful than a permanent green tick.

    The ten plugins therefore land in `devices_without_firmware`, show as "Firmware
    Unknown" on the dashboard, and link to UA's release notes so the check can be done
    by hand. Note the contrast the hardware draws: UAFX is delivered by UA Connect too
    -- its release notes open with "To update your pedal's firmware, use UA Connect" --
    and is published in full. Delivery through a vendor's own installer does not imply
    the version is unpublished, and assuming it did is what kept the pedals out of
    this scraper.
    """

    manufacturer_name = "Universal Audio"
    manufacturer_slug = "uaudio"
    manufacturer_website = "https://www.uaudio.com"

    # The closest thing UA has to a firmware page. It carries no versions, but it is
    # where a human would look, so it is what the device's "Details" link should open.
    RELEASE_NOTES_URL = (
        "https://help.uaudio.com/hc/en-us/articles/"
        "32181404310420-UAD-Native-Plug-Ins-Release-Notes"
    )

    # Map from plist CFBundleName to human-readable product name
    PLIST_NAME_MAP = {
        "uaudio_ampex_atr-102_tape": "Ampex ATR-102 Tape",
        "uaudio_distressor": "Distressor",
        "uaudio_dream_amp": "Dream Amp",
        "uaudio_galaxy_tape_echo": "Galaxy Tape Echo",
        "uaudio_lion_amp": "Lion Amp",
        "uaudio_polymax": "Polymax",
        "uaudio_ruby_amp": "Ruby Amp",
        "uaudio_sound_city_studios": "Sound City Studios",
        "uaudio_verve": "Verve",
        "uaudio_waterfall_rotary_speaker": "Waterfall Rotary Speaker",
    }

    KNOWN_PRODUCTS = [
        ("Ampex ATR-102 Tape", "vst_plugin", "https://www.uaudio.com/uad-plugins/mastering/ampex-atr-102.html"),
        ("Distressor", "vst_plugin", "https://www.uaudio.com/uad-plugins/compressors-limiters/empirical-labs-distressor.html"),
        ("Dream Amp", "vst_plugin", "https://www.uaudio.com/uad-plugins/guitar-bass/dream-65.html"),
        ("Galaxy Tape Echo", "vst_plugin", "https://www.uaudio.com/uad-plugins/delay/galaxy-tape-echo.html"),
        ("Lion Amp", "vst_plugin", "https://www.uaudio.com/uad-plugins/guitar-bass/lion-68.html"),
        ("Polymax", "vst_plugin", "https://www.uaudio.com/uad-plugins/instruments/polymax-synth.html"),
        ("Ruby Amp", "vst_plugin", "https://www.uaudio.com/uad-plugins/guitar-bass/ruby-63.html"),
        ("Sound City Studios", "vst_plugin", "https://www.uaudio.com/uad-plugins/reverbs/sound-city-studios.html"),
        ("Verve", "vst_plugin", "https://www.uaudio.com/uad-plugins/instruments/verve-analog-machines.html"),
        ("Waterfall Rotary Speaker", "vst_plugin", "https://www.uaudio.com/uad-plugins/modulation/waterfall-rotary-speaker.html"),
    ]

    # Zendesk Help Center, fetched by article id rather than by search. A search can
    # start returning a different article; an id cannot.
    ARTICLE_API = "https://help.uaudio.com/api/v2/help_center/articles/{}.json"
    UAFX_ARTICLE = "360062135192"
    OX_ARTICLE = "360001245246"

    UAFX_NOTES_URL = (
        "https://help.uaudio.com/hc/en-us/articles/360062135192-UAFX-Firmware-Release-Notes"
    )
    OX_NOTES_URL = (
        "https://help.uaudio.com/hc/en-us/articles/"
        "360001245246-OX-Amp-Top-Box-Firmware-Release-Notes"
    )

    # The shop's Shopify collection, so the pedal list is discovered rather than
    # transcribed and a product added next year appears without an edit here.
    PEDALS_URL = "https://www.uaudio.com/collections/guitar-pedals/products.json?limit=250"
    UAFX_TAG = "category guitar:UAFX Pedals"
    OX_PRODUCT = "OX Amp Top Box"

    # "UAFX Version 2.0.2" / "December 22, 2025"
    UAFX_VERSION = re.compile(r"UAFX\s+Version\s+([\d.]+)\s*$", re.I)
    # "OX Firmware v1.2 — November 12, 2019", both halves in one heading.
    OX_ENTRY = re.compile(r"OX\s+Firmware\s+v([\d.]+)\s*[—–-]\s*(.+)$", re.I)
    LONG_DATE = re.compile(r"^([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})$")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pedals: Optional[List[dict]] = None
        self._notes: Dict[str, List[ScrapedFirmware]] = {}

    @staticmethod
    def _parse_long_date(text: str) -> Optional[datetime]:
        try:
            return datetime.strptime(text.strip(), "%B %d, %Y")
        except ValueError:
            return None

    async def _fetch_article(self, article_id: str) -> Optional[str]:
        raw = await self.fetch_page(self.ARTICLE_API.format(article_id))
        if not raw:
            return None
        try:
            return (json.loads(raw).get("article") or {}).get("body")
        except ValueError:
            return None

    def _parse_uafx(self, body: str) -> List[ScrapedFirmware]:
        """Version in an h2, date in the h4 below it, changes in the list after."""
        soup = self.parse_html(body)
        versions: List[ScrapedFirmware] = []
        seen = set()

        for heading in soup.find_all(["h2", "h3"]):
            match = self.UAFX_VERSION.search(heading.get_text(" ", strip=True))
            if not match or match.group(1) in seen:
                continue
            seen.add(match.group(1))

            release_date = None
            changelog = None
            for sibling in heading.find_next_siblings():
                text = sibling.get_text(" ", strip=True)
                if release_date is None and self.LONG_DATE.match(text):
                    release_date = self._parse_long_date(text)
                    continue
                if sibling.name == "ul":
                    changelog = text[:500] or None
                    break
                if sibling.name in ("h2", "h3"):
                    break

            versions.append(
                ScrapedFirmware(
                    version=match.group(1),
                    release_date=release_date,
                    changelog=changelog,
                )
            )
        return versions

    def _parse_ox(self, body: str) -> List[ScrapedFirmware]:
        """Version and date in one heading, which is also what excludes the how-to."""
        soup = self.parse_html(body)
        versions: List[ScrapedFirmware] = []
        seen = set()

        for heading in soup.find_all(["h2", "h3", "h4"]):
            match = self.OX_ENTRY.search(heading.get_text(" ", strip=True))
            if not match:
                continue
            version, tail = match.group(1), match.group(2)
            release_date = self._parse_long_date(tail)
            if release_date is None or version in seen:
                # No date means this is the install instructions, not a release.
                continue
            seen.add(version)

            body_node = heading.find_next_sibling()
            versions.append(
                ScrapedFirmware(
                    version=version,
                    release_date=release_date,
                    changelog=body_node.get_text(" ", strip=True)[:500] if body_node else None,
                )
            )
        return versions

    async def _load_pedals(self) -> Optional[List[dict]]:
        if self._pedals is not None:
            return self._pedals
        raw = await self.fetch_page(self.PEDALS_URL)
        if not raw:
            return None
        try:
            products = json.loads(raw).get("products") or []
        except ValueError:
            return None

        pedals = []
        for product in products:
            title = (product.get("title") or "").strip()
            if not title:
                continue
            tags = product.get("tags") or []
            if self.UAFX_TAG in tags:
                pedals.append({"name": title, "kind": "uafx"})
            elif title == self.OX_PRODUCT:
                pedals.append({"name": title, "kind": "ox"})
        self._pedals = pedals
        return self._pedals

    async def fetch_device_list(self) -> ScraperResult:
        pedals = await self._load_pedals()
        if pedals is None:
            return ScraperResult(
                success=False, error=f"Failed to fetch {self.PEDALS_URL}"
            )

        devices = [
            ScrapedDevice(
                name=name,
                category=category,
                # firmware_page_url is what a device's "Details" link opens, so it
                # points at the release notes rather than the shop page.
                firmware_page_url=self.RELEASE_NOTES_URL,
                product_url=url,
            )
            for name, category, url in self.KNOWN_PRODUCTS
        ]
        devices += [
            ScrapedDevice(
                name=pedal["name"],
                category="guitar_pedal",
                firmware_page_url=(
                    self.UAFX_NOTES_URL if pedal["kind"] == "uafx" else self.OX_NOTES_URL
                ),
                product_url="https://www.uaudio.com/collections/guitar-pedals",
            )
            for pedal in pedals
        ]
        return ScraperResult(success=True, devices=devices)

    async def _release_notes(self, kind: str) -> Optional[List[ScrapedFirmware]]:
        """One article per kind, fetched once and reused across the products it covers."""
        if kind in self._notes:
            return self._notes[kind]

        article_id = self.UAFX_ARTICLE if kind == "uafx" else self.OX_ARTICLE
        body = await self._fetch_article(article_id)
        if body is None:
            return None

        parsed = self._parse_uafx(body) if kind == "uafx" else self._parse_ox(body)
        self._notes[kind] = parsed
        return parsed

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        """Hardware reads its release notes; the plugins report nothing, as before.

        Reporting nothing is success rather than failure: the fetch did not break, the
        product simply has no discoverable version. The service keeps those apart --
        `devices_failed` against `devices_without_firmware` -- and conflating them
        would either hide a real breakage or raise a false alarm every run.
        """
        pedals = await self._load_pedals()
        kind = None
        if pedals:
            kind = next(
                (p["kind"] for p in pedals if p["name"] == device_name), None
            )

        if kind is None:
            # A UADX plugin, or a pedal the shop no longer lists.
            return ScraperResult(success=True, firmware_versions=[])

        versions = await self._release_notes(kind)
        if versions is None:
            return ScraperResult(
                success=False,
                error=f"Failed to fetch UA release notes for {device_name}",
            )
        return ScraperResult(success=True, firmware_versions=versions)
