import json
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, unquote

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)


class SSLScraper(BaseScraper):
    """Solid State Logic -- SSL 360°, its plug-ins and the USB interfaces' firmware, from three help-centre articles.

    solidstatelogic.com's downloads page holds no versions; support.solidstatelogic.com
    (Zendesk) does, in three articles found by exact title through the search API:

    **"SSL 360° Downloads and Release Notes"** -- one ``<h2>V2.1.12</h2>`` per release of
    the SSL 360° app, and under it a release line written four ways: "Released: 11th
    August 2026", "Released June 2025", "<em>Released January 2025</em>", "<strong>Released
    October 2023</strong>". A month alone is stored as the first of it. V1.6.13 has no
    release line and is stored undated. Each release's table of bundled plug-in versions
    is left out of its notes.

    **"SSL Plug-in Downloads"** -- a table row per plug-in, "AutoEQ v1.0.41", with Mac and
    Windows download buttons. **The label lags the file**: AutoEQ's row says v1.0.41 and
    its installer is "SSL autoEQ macOS v1.0.43 Installer.dmg". The version is read from the
    download file names, the newest of the two platforms, and from the label only when
    no file carries one. The sonible add-on editions ("4K G v1.3.1 (sonible add-on)") are
    separate products from "4K G v1.2.7". Undated: the download folders are named like
    "2026.07.23 - v2.0.20", but a folder name is not a release note. The "Legacy plugin
    downloads" article is not read -- its products are the older builds of these.

    **"SSL 2/2+ MKII Firmware Update"** -- the history of the SSL USB Audio Firmware
    Updater, whose packages each name the firmware they carry:

        <h2>V1.5</h2> ... <p><em>SSL 2 MK II/SSL 2+ MK II Firmware Number: V1.16 (UID 31852)</em></p>
        <h2>V1.3</h2> ... <p><em>PURE DRIVE QUAD and OCTO Firmware Version Number: V1.11 ...</em></p>

    The package number is not the firmware's. Each firmware line is split into its
    models -- "SSL 2/2+" is SSL 2 and SSL 2+ (the MKI, which stops at V1.10), "PURE DRIVE
    QUAD and OCTO" is PureDrive Quad and PureDrive Octo -- and a model's newest package
    gives its current firmware. The BiG SiX, PureDrive and SSL 2/2+ MKI articles carry the
    same history, word for word. Undated.

    Not read, checked 2026-09-15: Alpha-Link, Delta-Link and X-Rack firmware articles --
    discontinued units whose last firmware shipped by 2011. SSL 12, SSL 18, UF8, UF1 and
    UC1 firmware ships inside SSL 360° and is not numbered anywhere.

    Any of the three articles missing fails the scrape, since the products it covers would
    otherwise silently stop updating.
    """

    manufacturer_name = "Solid State Logic"
    manufacturer_slug = "ssl"
    manufacturer_website = "https://www.solidstatelogic.com"

    SEARCH_URL = "https://support.solidstatelogic.com/api/v2/help_center/articles/search.json?query={query}&per_page=10"
    RELEASE_NOTES = "SSL 360° Downloads and Release Notes"
    PLUGINS = "SSL Plug-in Downloads"
    INTERFACES = "SSL 2/2+ MKII Firmware Update"
    APP_NAME = "SSL 360°"

    RELEASE_HEADING = re.compile(r"^V(?P<version>\d+(?:\.\d+)+)$")
    RELEASED = re.compile(
        r"^Released:?\s+(?:(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+)?(?P<month>[A-Za-z]+)\s+(?P<year>\d{4})$", re.I
    )
    PLUGIN_LABEL = re.compile(r"^(?P<name>.+?)\s+[vV](?P<version>\d+(?:\.\d+)+)(?:\s*(?P<edition>\(.+\)))?$")
    FILE_VERSION = re.compile(r"[vV](\d+(?:\.\d+)+)")
    FIRMWARE_LINE = re.compile(
        r"^(?P<models>.+?)\s+Firmware(?:\s+Version)?(?:\s+Number)?:\s*V(?P<version>\d+(?:\.\d+)+)", re.I
    )
    MODEL_RENAMES = {"PURE DRIVE QUAD": "PureDrive Quad", "PURE DRIVE OCTO": "PureDrive Octo"}
    NOTES_LIMIT = 4000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._devices: Optional[Dict[str, Tuple[str, str, List[ScrapedFirmware]]]] = None

    @classmethod
    def search_url(cls, title: str) -> str:
        return cls.SEARCH_URL.format(query=quote(title))

    # --- parsing ------------------------------------------------------------

    @staticmethod
    def _text(element) -> str:
        return " ".join(element.get_text(" ").split())

    @staticmethod
    def _version_key(version: str) -> Tuple[int, ...]:
        return tuple(int(part) for part in version.split("."))

    def _section(self, heading) -> List:
        """The elements after an <h2> up to the next <h2>."""
        elements = []
        for sibling in heading.find_next_siblings():
            if sibling.name == "h2":
                break
            elements.append(sibling)
        return elements

    def _parse_date(self, text: str) -> Optional[datetime]:
        matched = self.RELEASED.match(text)
        if not matched:
            return None
        try:
            return datetime.strptime(
                f"{matched.group('month')[:3].title()} {matched.group('day') or 1} {matched.group('year')}", "%b %d %Y"
            )
        except ValueError:
            return None

    def _parse_release_notes(self, html: str) -> List[ScrapedFirmware]:
        releases: List[ScrapedFirmware] = []
        for heading in self.parse_html(html).find_all("h2"):
            matched = self.RELEASE_HEADING.match(self._text(heading))
            if not matched:
                continue
            date: Optional[datetime] = None
            lines: List[str] = []
            for element in self._section(heading):
                for block in [element] if element.name in ("p", "li", "h4") else element.find_all(["p", "li", "h4"]):
                    text = self._text(block)
                    released = self._parse_date(text)
                    if released:
                        date = released
                    elif text:
                        lines.append(text)
            releases.append(ScrapedFirmware(version=matched.group("version"), release_date=date,
                                            changelog="\n".join(lines)[: self.NOTES_LIMIT] or None))
        return releases

    def _parse_plugins(self, html: str) -> Dict[str, str]:
        plugins: Dict[str, str] = {}
        for row in self.parse_html(html).find_all("tr"):
            cells = row.find_all("td")
            label = self.PLUGIN_LABEL.match(self._text(cells[0])) if cells else None
            if not label:
                continue
            name = f"{label.group('name')} {label.group('edition')}" if label.group("edition") else label.group("name")
            if name == self.APP_NAME:
                continue
            from_files = []
            for link in row.find_all(attrs={"data-link": True}):
                filename = unquote(link["data-link"].strip().rsplit("/", 1)[-1])
                found = self.FILE_VERSION.search(filename)
                if found:
                    from_files.append(found.group(1))
            version = max(from_files, key=self._version_key) if from_files else label.group("version")
            plugins.setdefault(name, version)
        return plugins

    def _models(self, text: str) -> List[str]:
        parts = [part.strip() for part in re.split(r"\s*/\s*|\s+and\s+", text) if part.strip()]
        models = []
        for part in parts:
            if " " not in part and " " in parts[0]:
                part = f"{parts[0].rsplit(' ', 1)[0]} {part}"
            part = re.sub(r"\bMK\s+II\b", "MKII", part)
            models.append(self.MODEL_RENAMES.get(part.upper(), part))
        return models

    def _parse_interfaces(self, html: str) -> Dict[str, List[ScrapedFirmware]]:
        firmware: Dict[str, List[ScrapedFirmware]] = {}
        for heading in self.parse_html(html).find_all("h2"):
            if not self.RELEASE_HEADING.match(self._text(heading)):
                continue
            section = self._section(heading)
            blocks = [b for element in section
                      for b in ([element] if element.name in ("p", "li") else element.find_all(["p", "li"]))]
            texts = [self._text(block) for block in blocks]
            line = next((self.FIRMWARE_LINE.match(text) for text in texts if self.FIRMWARE_LINE.match(text)), None)
            if not line:
                continue
            notes = [text for text in texts if text and not self.FIRMWARE_LINE.match(text)
                     and text != "Downloads" and not text.startswith("Update Package")]
            for model in self._models(line.group("models")):
                firmware.setdefault(model, []).append(ScrapedFirmware(
                    version=line.group("version"), release_date=None,
                    changelog="\n".join(notes)[: self.NOTES_LIMIT] or None,
                ))
        return firmware

    # --- loading ------------------------------------------------------------

    async def _article(self, title: str) -> Optional[Tuple[str, str]]:
        body = await self.fetch_page(self.search_url(title))
        try:
            results = json.loads(body).get("results") or [] if body else []
        except (ValueError, AttributeError):
            return None
        article = next((a for a in results if (a.get("title") or "").strip() == title and a.get("body")), None)
        return (article.get("html_url") or "", article["body"]) if article else None

    async def _load(self) -> Optional[Dict[str, Tuple[str, str, List[ScrapedFirmware]]]]:
        if self._devices is not None:
            return self._devices
        articles = {}
        for title in (self.RELEASE_NOTES, self.PLUGINS, self.INTERFACES):
            articles[title] = await self._article(title)
            if articles[title] is None:
                logger.warning("SSL help centre article %r was not found", title)
                return None
        devices: Dict[str, Tuple[str, str, List[ScrapedFirmware]]] = {}
        url, body = articles[self.RELEASE_NOTES]
        app = self._parse_release_notes(body)
        if app:
            devices[self.APP_NAME] = (url, "other", app)
        url, body = articles[self.PLUGINS]
        for name, version in self._parse_plugins(body).items():
            devices.setdefault(name, (url, "vst_plugin", [ScrapedFirmware(version=version, release_date=None)]))
        url, body = articles[self.INTERFACES]
        for model, releases in self._parse_interfaces(body).items():
            devices.setdefault(model, (url, "audio_interface", releases))
        self._devices = devices or None
        return self._devices

    async def fetch_device_list(self) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error="SSL help centre articles did not load")
        return ScraperResult(
            success=True,
            devices=[ScrapedDevice(name=name, category=category, firmware_page_url=url, product_url=url)
                     for name, (url, category, _releases) in devices.items()],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        devices = await self._load()
        if not devices:
            return ScraperResult(success=False, error="SSL help centre articles did not load")
        entry = devices.get(device_name)
        return ScraperResult(success=True, firmware_versions=entry[2] if entry else [])
