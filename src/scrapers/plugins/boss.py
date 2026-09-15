import re

from src.scrapers.base import BaseScraper
from src.scrapers.roland_group import SystemProgramMixin


class BossScraper(SystemProgramMixin, BaseScraper):
    """Boss pedals, read the same way as Roland because it is the same site.

    Boss is a Roland brand and its Updates & Drivers pages are identical in shape, so
    the index, the parsing and the batching live in SystemProgramMixin and both use
    it. The products come from the US Updates & Drivers index, 126 of them, in two
    daily batches.

    The previous parser searched the listing for a date in two formats and found none,
    because that page has no dates at all -- 3,656 characters of text and not one.
    The dates are on the detail page behind the System Program link, along with the
    rest of the history. It also had to guess which version on the page was the
    firmware, competing with an IR Loader, four USB drivers and a bundled copy of
    Chromium Embedded Framework.

    Set `BOSS_FULL_SWEEP=1` to read both batches in one run.
    """

    manufacturer_name = "Boss"
    manufacturer_slug = "boss"
    manufacturer_website = "https://www.boss.info"

    INDEX_URL = "https://www.boss.info/us/support/updates_drivers/"

    # Two batches of ~63: about 90 requests and two minutes a run.
    BATCHES = 2
    FULL_SWEEP_ENV = "BOSS_FULL_SWEEP"

    # The index writes the Katanas in capitals; the rows were catalogued without.
    RENAMES = {
        "KATANA-100 MkII": "Katana-100 MkII",
        "KATANA-Artist MkII": "Katana-Artist MkII",
    }

    NOT_PEDALS = re.compile(
        r"amplifier|amplification|recorder|recording|studio|mixer|player|load box|amp expander",
        re.I,
    )

    def _category(self, subtitle: str) -> str:
        """From the index's subtitle. Boss is pedals unless the subtitle says otherwise.

        Amps, recorders and mixers are "other"; the Dr. Rhythm and Dr. Sample
        machines are instruments; wireless footswitches and expression pedals control
        rather than process. Only used when a row is created.
        """
        text = subtitle.lower()
        if "expression pedal" in text or "footswitch" in text:
            return "midi_controller"
        if self.NOT_PEDALS.search(text):
            return "other"
        if re.search(r"dr\. rhythm|dr\. sample|sampling workstation", text):
            return "synthesizer"
        return "guitar_pedal"
