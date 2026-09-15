import logging
import re
from datetime import datetime
from typing import Dict, List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

logger = logging.getLogger(__name__)

MONTHS = {name: number for number, name in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


class WavesScraper(BaseScraper):
    """Waves -- its plug-in generations and the Waves Central installer, from the release notes.

    Waves publishes no per-plug-in version anywhere public: individual builds are
    resolved inside its installer. What it does publish is `/downloads/release-notes`,
    a feed of dated posts in one tab per generation, V17 back to V9, covering
    everything it ships -- SoundGrid servers, the eMotion LV1 console, remote apps, new
    plug-ins -- and two kinds of release worth tracking:

        <p class="waves-h4">June 23, 2026</p>
        <p class="waves-p"><strong>All Waves Plugins: Across-the-board software update to V17</strong></p>

        <p class="waves-h4">August 2, 2026</p>
        <ul><li><strong>Waves Central v17.0.4</strong> is now available with the following updates: ...

    So there are two devices: **"Waves Plugins"**, whose versions are the generations
    every plug-in moves to together (17 back to 9.6, with half-steps like 12.7), and
    **"Waves Central"**, the installer every Waves product updates through.

    **A release is a line that begins with it.** A post's title and each of its
    top-level bullets are lines. "All Waves SoundGrid applications, firmware and
    drivers: Across-the-board software update to V12" is not a plug-in generation, and
    "SuperRack v12.2 now requires Waves Central 12.0.7" is not a Central release.
    Both are written several ways over eleven years: "Across-the-board software update
    to V17" and "to version 10.", "Version 9.91 across-the-board update of all Waves
    plugins"; "Waves Central v15.0.3 (Windows Only)", "Waves Central Waves Central
    v15.2.2", "Waves Central: New Version (V12.0.15)", "Waves Central 1.3.7.8:".

    **A generation is dated by its first post.** V16 shipped on June 23, 2025 and has a
    second post on December 15; V15 did the same in 2024.

    **Posts are laid out several ways.** The date is a `p.waves-h4`, or in the oldest
    tabs a `p.waves-p` holding only the date; a title is a second `waves-h4` or a
    `waves-p`; and a bullet's sub-list is sometimes the list's next child rather than
    inside the bullet. The page carries most tabs twice, which changes nothing: a
    version keeps its earliest date. Dates are written "June 23, 2026" and "October
    11th, 2021".

    **The site sits behind Imperva.** On 2026-09-14 a plain fetch returned the page
    for a morning of probing, then a 212-byte challenge script; a browser fetch passed
    it. So the plain fetch is tried first, and the browser used when the release notes
    are not in the answer.
    """

    manufacturer_name = "Waves"
    manufacturer_slug = "waves"
    manufacturer_website = "https://www.waves.com"

    RELEASE_NOTES_URL = "https://www.waves.com/downloads/release-notes"
    PLUGINS = "Waves Plugins"
    CENTRAL = "Waves Central"
    CATEGORIES = {PLUGINS: "vst_plugin", CENTRAL: "vst_plugin"}

    DATE = re.compile(r"^([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})$")
    GENERATIONS = (
        re.compile(r"^All\s+Waves\s+plugins:\s*Across-the-board\s+software\s+update\s+to\s+(?:V|version\s+)"
                   r"(?P<version>\d+(?:\.\d+)?)(?![\d.]*\d)", re.I),
        re.compile(r"^Version\s+(?P<version>\d+(?:\.\d+)?)\s+across-the-board\s+update\s+of\s+all\s+Waves\s+plugins", re.I),
        re.compile(r"^Across\s+the\s+board\s+release\s+of\s+all\s+Waves\s+plugins\s+V(?P<version>\d+(?:\.\d+)?)", re.I),
    )
    CENTRAL_RELEASE = re.compile(
        r"^(?:Waves\s+Central\s*)+(?::\s*New\s+Version\s*\(|:\s*The\s+new\s+version\s+)?v?"
        r"(?P<version>\d+(?:\.\d+)+)(?![\d.]*\d)", re.I)
    NOTES_LIMIT = 4000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._products: Optional[Dict[str, List[ScrapedFirmware]]] = None

    def _date(self, text: str) -> Optional[datetime]:
        matched = self.DATE.match(text)
        if not matched:
            return None
        month = MONTHS.get(matched.group(1)[:3].lower())
        try:
            return datetime(int(matched.group(3)), month, int(matched.group(2))) if month else None
        except ValueError:
            return None

    def _lines(self, date_paragraph) -> List[str]:
        """A post's title and top-level bullets, up to the next post's date.

        A bullet's sub-list is sometimes written as the next child of the list rather
        than inside the bullet, so it is read into the bullet before it.
        """
        lines: List[str] = []
        for sibling in date_paragraph.find_next_siblings(["p", "ul"]):
            text = " ".join(sibling.get_text(" ").split())
            if sibling.name == "p":
                if self._date(text):
                    break
                lines.append(text)
                continue
            for child in sibling.find_all(["li", "ul"], recursive=False):
                text = " ".join(child.get_text(" ").split())
                if child.name == "ul" and lines:
                    lines[-1] = f"{lines[-1]} {text}"
                else:
                    lines.append(text)
        return [line for line in lines if line]

    def _parse_release_notes(self, html: str) -> Dict[str, List[ScrapedFirmware]]:
        soup = self.parse_html(html)
        found: Dict[str, Dict[str, ScrapedFirmware]] = {self.PLUGINS: {}, self.CENTRAL: {}}
        for paragraph in soup.select("section[id^='ctnt-'] p"):
            released = self._date(" ".join(paragraph.get_text(" ").split()))
            if released is None:
                continue
            lines = self._lines(paragraph)

            for position, line in enumerate(lines):
                for device, patterns in ((self.PLUGINS, self.GENERATIONS), (self.CENTRAL, (self.CENTRAL_RELEASE,))):
                    matched = next((m for m in (pattern.match(line) for pattern in patterns) if m), None)
                    if not matched:
                        continue
                    version = matched.group("version")
                    # A generation's post is all about the generation; a Central bullet is one of several.
                    notes = "\n".join(lines[position:]) if device == self.PLUGINS else line
                    existing = found[device].get(version)
                    if existing is None or released < existing.release_date:
                        found[device][version] = ScrapedFirmware(
                            version=version, release_date=released, changelog=notes[: self.NOTES_LIMIT],
                        )

        return {
            device: sorted(versions.values(), key=lambda fw: fw.release_date, reverse=True)
            for device, versions in found.items() if versions
        }

    async def _load(self) -> Optional[Dict[str, List[ScrapedFirmware]]]:
        if self._products is None:
            html = await self.fetch_page(self.RELEASE_NOTES_URL)
            if not html or "ctnt-" not in html:
                logger.info("Waves release notes not in the plain fetch; trying the browser")
                html = await self.fetch_page_js(self.RELEASE_NOTES_URL, wait_for_timeout=8000)
            products = self._parse_release_notes(html) if html else {}
            self._products = products if self.PLUGINS in products else None
        return self._products

    async def fetch_device_list(self) -> ScraperResult:
        products = await self._load()
        if not products:
            return ScraperResult(success=False, error=f"No Waves plug-in generations found at {self.RELEASE_NOTES_URL}")
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category=self.CATEGORIES[name],
                    firmware_page_url=self.RELEASE_NOTES_URL,
                    product_url=self.RELEASE_NOTES_URL,
                )
                for name in products
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        products = await self._load()
        if not products:
            return ScraperResult(success=False, error=f"No Waves plug-in generations found at {self.RELEASE_NOTES_URL}")
        return ScraperResult(success=True, firmware_versions=list(products.get(device_name, [])))
