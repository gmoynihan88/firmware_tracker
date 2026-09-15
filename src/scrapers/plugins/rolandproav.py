import re

from src.scrapers.base import BaseScraper
from src.scrapers.roland_group import SystemProgramMixin


class RolandProAVScraper(SystemProgramMixin, BaseScraper):
    """Roland Pro AV: live mixing consoles, REAC units, video switchers and recorders.

    proav.roland.com is the same site as roland.com in a different skin, so the index,
    the listing, the detail page and its dated UPDATE HISTORY are read by
    SystemProgramMixin, as for Roland and Boss. Its own manufacturer, because the
    catalogue already has a Roland (instruments) and names are unique.

    The Updates & Drivers index lists 95 products on 2026-09-15; 59 publish firmware,
    306 of their 320 versions dated.
    robots.txt disallows `/support/` at the site root only, and the pages read here are
    all under `/global/support/`.

    **Pro AV words the firmware four ways**, and the mixin's "System Program" alone
    missed four of the mixers:

        M-5000 System Program (Ver.1.520)
        M-480 System Update Ver.1.610
        M-400 System Software Update Ver.2.321
        M-48 System Update Version 1.010

    The pattern still requires "System", so "M-480 RCS Ver.1.610 for Windows" -- the
    remote-control editor, numbered in step with the console -- and the V-Mixer USB
    drivers beside it are not read. UVC-01 numbers its firmware by date,
    "Ver.2024.06.11"; that is the version as Roland publishes it, not a release date.

    One full pass is about 200 seconds, inside a scrape's budget, so every product is
    checked every run and there are no batches.
    """

    manufacturer_name = "Roland Pro AV"
    manufacturer_slug = "rolandproav"
    manufacturer_website = "https://proav.roland.com"

    INDEX_URL = "https://proav.roland.com/global/support/updates_drivers/"

    SYSTEM_PROGRAM = re.compile(
        r"System\s+(?:Program|Software\s+Update|Update)\s*\(?\s*(?:Ver\.?|Version)\s*(\d+(?:\.\d+)+)\s*\)?",
        re.I,
    )
