import re

from src.scrapers.base import BaseScraper
from src.scrapers.roland_group import SystemProgramMixin


class RolandScraper(SystemProgramMixin, BaseScraper):
    """Roland instruments, read from each product's System Program page.

    The products come from the global Updates & Drivers index, 580 of them, read in
    six daily batches; see `roland_group` for the index, the batching and why.

    The Updates & Drivers listing carries two kinds of version and the previous
    parser could not tell them apart. Alongside "MC-101 System Program (Ver.1.82)",
    which is the instrument's firmware, sit half a dozen USB driver entries --
    "MC-101 Driver Ver.1.0.3 for macOS Sonoma 14.x or later" -- and a pattern
    scanning for the first `Ver.` on the page can land on either.

    That listing has no dates at all. The System Program entry links to a detail page
    that does, holding the full history rather than only the current release:

        [ Ver.1.82 ] JUN 2023
        Bug Fixes ...
        [ Ver.1.81 ] NOV 2022

    So each product with firmware costs one extra fetch, and yields every version
    Roland has published for it with a date and its changelog.

    Roland dates to the month. These are stored as the first of that month, which is
    the usual way to record month precision -- worth knowing before reading a day
    number as exact.

    Versions are genuinely shared across a platform family: MC-101, MC-707 and
    VERSELAB MV-1 all run System Program 1.82. That is not the duplication bug it
    resembles; it was checked against all three pages.

    Set `ROLAND_FULL_SWEEP=1` to read all six batches in one run -- the catch-up path,
    1,945s when measured, far longer than the scheduler's hard timeout.
    """

    manufacturer_name = "Roland"
    manufacturer_slug = "roland"
    manufacturer_website = "https://www.roland.com"

    INDEX_URL = "https://www.roland.com/global/support/updates_drivers/"

    # Six batches of ~97: about 140 requests and three minutes a run, and every
    # product re-read within six days.
    BATCHES = 6
    FULL_SWEEP_ENV = "ROLAND_FULL_SWEEP"

    # Every name the sixteen catalogued products were given matches the index exactly.
    RENAMES = {}

    SYNTH_WORDS = re.compile(
        r"synth|groove|sampl|workstation|sound module|drum|percussion|rhythm|beat|"
        r"bass ?line|keyboard|piano|organ|accordion|arranger|keytar|wind instrument|"
        r"\bpad\b|modular|orchestrator",
        re.I,
    )

    def _category(self, subtitle: str) -> str:
        """From the index's subtitle -- "Digital Piano", "USB Audio Interface", "V-Drums".

        Controllers and pedals first, so "Audio Interface & MIDI Keyboard Controller"
        is a controller and "Expression Pedal" is not a synthesizer. Only used when a
        row is created.
        """
        text = subtitle.lower()
        if "controller" in text or "pedal" in text:
            return "midi_controller"
        if "interface" in text or "audio capture" in text:
            return "audio_interface"
        if "amplifier" in text:
            return "other"
        if self.SYNTH_WORDS.search(text):
            return "synthesizer"
        return "other"
