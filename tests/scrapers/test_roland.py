ROLAND_LISTING = """
<h5><a href="/global/support/by_product/mc-101/updates_drivers/abc/">MC-101 System Program (Ver.1.82)</a></h5>
<h5><a href="/d1/">MC-101 Driver Ver.1.0.3 for macOS Sonoma 14.x or later</a></h5>
<h5><a href="/d2/">MC-101 Driver Ver.1.0.2 for Windows 10/11</a></h5>
"""


ROLAND_DETAIL = """
<div class="details">
  <b>HOW TO TELL THE VERSION</b>
  Before you start, check the system program version of your MC-101.
  <b>UPDATE HISTORY</b>
  [ Ver.1.82 ] JUN 2023 Bug Fixes. Arpeggiator fix.
  [ Ver.1.81 ] NOV 2022 Bug Fixes. SDZ loading fix.
</div>
"""


def test_roland_picks_the_system_program_not_a_driver():
    """The listing puts USB drivers beside the firmware, both written "Ver.".

    A pattern taking the first version on the page can land on Ver.1.0.3, which is a
    macOS driver rather than anything the instrument runs.
    """
    from src.scrapers.plugins.roland import RolandScraper

    version, url = RolandScraper()._system_program_link(ROLAND_LISTING)

    assert version == "1.82"
    assert url.endswith("/mc-101/updates_drivers/abc/")


def test_roland_accepts_the_bare_system_program_form():
    """AIRA Compacts write it without parentheses.

    Requiring them silently returned nothing for J-6 and T-8, which do publish
    firmware -- a stricter pattern reading as "this product has none".
    """
    from src.scrapers.plugins.roland import RolandScraper

    bare = '<a href="/x/">J-6 System Program Ver.1.02</a>'
    assert RolandScraper()._system_program_link(bare)[0] == "1.02"

    spaced = '<a href="/x/">JUPITER-X System Program ( Ver.3.03 )</a>'
    assert RolandScraper()._system_program_link(spaced)[0] == "3.03"


def test_roland_reads_the_whole_update_history():
    """The detail page carries every release, not just the current one.

    Roland dates to the month, stored as the first of it.
    """
    from src.scrapers.plugins.roland import RolandScraper

    versions = RolandScraper()._parse_history(ROLAND_DETAIL)

    assert [f.version for f in versions] == ["1.82", "1.81"]
    assert versions[0].release_date.strftime("%Y-%m-%d") == "2023-06-01"
    assert versions[1].release_date.strftime("%Y-%m-%d") == "2022-11-01"
    # Each entry keeps its own notes rather than the whole page.
    assert "Arpeggiator" in versions[0].changelog
    assert "Arpeggiator" not in versions[1].changelog
    # The "how to tell the version" prose above the history is not a release.
    assert len(versions) == 2


def test_boss_and_roland_share_one_parser():
    """Boss is a Roland brand and the pages are identical in shape.

    Verified by running Roland's link finder against a real Boss page before the
    parsing was moved into a mixin both use.
    """
    from src.scrapers.plugins.boss import BossScraper
    from src.scrapers.plugins.roland import RolandScraper
    from src.scrapers.roland_group import SystemProgramMixin

    assert issubclass(BossScraper, SystemProgramMixin)
    assert issubclass(RolandScraper, SystemProgramMixin)
