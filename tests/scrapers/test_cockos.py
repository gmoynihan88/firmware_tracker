import pytest

from tests.support import _stub_fetch


REAPER_CHANGELOG = """v7.80 - September 13 2026
  + CLAP: support CLAP_EVENT_IS_LIVE
  + Docks: fix macOS flicker
v6.12c - June 15 2020
  + Fixed a regression in 6.12
v4.21 - April 5 2012
  + API: plug-in state api supports larger chunks
v4.21 - March 23 2012
  + JS: fixed MIDI bus handling
v4.0 - August 3 2011

4.0 headline changes:

  + Dockers and toolbars are freely dockable
    (drag tabs to rearrange)
v4.0rc5 - August 2 2011
  + release-candidate fix that is not a release
v2.013 - November 27ish 2007
  + preliminary basic MMC response
v2.0b16 - September 30 2007
  + beta fix that is not a release
v0.41 - Dec 26 2005
  + made accidental item moves less likely
"""


def test_reaper_reads_releases_and_skips_prereleases():
    """rc and b builds are not releases; a single trailing letter (6.12c) is."""
    from src.scrapers.plugins.cockos import CockosScraper

    versions = CockosScraper()._parse_changelog(REAPER_CHANGELOG)

    assert [fw.version for fw in versions] == ["7.80", "6.12c", "4.21", "4.0", "2.013", "0.41"]
    assert versions[0].release_date.date().isoformat() == "2026-09-13"
    assert versions[-1].release_date.date().isoformat() == "2005-12-26"
    assert all("not a release" not in (fw.changelog or "") for fw in versions)


def test_reaper_keeps_section_lines_inside_an_entry():
    """4.0's notes open at the margin with "4.0 headline changes:"."""
    from src.scrapers.plugins.cockos import CockosScraper

    four = next(fw for fw in CockosScraper()._parse_changelog(REAPER_CHANGELOG) if fw.version == "4.0")

    assert four.changelog.splitlines() == [
        "4.0 headline changes:",
        "+ Dockers and toolbars are freely dockable",
        "(drag tabs to rearrange)",
    ]


def test_reaper_reads_misspelled_months():
    """The log spells February "Feburary" and "Februrary"; strict names left them undated."""
    from src.scrapers.plugins.cockos import CockosScraper

    versions = CockosScraper()._parse_changelog(
        "v7.32 - Feburary 1 2025\n  + fix\nv6.04 - Februrary 21 2020\n  + fix\nv0.41 - Dec 26 2005\n  + fix\n"
    )

    assert [(fw.version, fw.release_date.date().isoformat()) for fw in versions] == [
        ("7.32", "2025-02-01"), ("6.04", "2020-02-21"), ("0.41", "2005-12-26"),
    ]


def test_reaper_leaves_an_approximate_date_undated():
    """ "November 27ish 2007" is the vendor's approximation, not a day to record."""
    from src.scrapers.plugins.cockos import CockosScraper

    approx = next(fw for fw in CockosScraper()._parse_changelog(REAPER_CHANGELOG) if fw.version == "2.013")

    assert approx.release_date is None
    assert approx.changelog == "+ preliminary basic MMC response"


def test_reaper_dates_a_repeated_version_by_its_first_release():
    from src.scrapers.plugins.cockos import CockosScraper

    repeated = [fw for fw in CockosScraper()._parse_changelog(REAPER_CHANGELOG) if fw.version == "4.21"]

    assert len(repeated) == 1
    assert repeated[0].release_date.date().isoformat() == "2012-03-23"
    assert repeated[0].changelog.splitlines() == [
        "+ API: plug-in state api supports larger chunks",
        "+ JS: fixed MIDI bus handling",
    ]


@pytest.mark.asyncio
async def test_reaper_is_one_device_from_one_fetch():
    from src.scrapers.plugins.cockos import CockosScraper as C

    scraper = C()
    asked = _stub_fetch(scraper, {C.CHANGELOG_URL: REAPER_CHANGELOG})

    devices = (await scraper.fetch_device_list()).devices
    result = await scraper.fetch_firmware_versions(devices[0].name, devices[0].firmware_page_url)

    assert asked == [C.CHANGELOG_URL]
    assert [(d.name, d.category) for d in devices] == [("REAPER", "vst_plugin")]
    assert result.firmware_versions[0].version == "7.80"


@pytest.mark.asyncio
async def test_reaper_fails_loudly_without_the_changelog():
    from src.scrapers.plugins.cockos import CockosScraper as C

    scraper = C()
    _stub_fetch(scraper, {})

    assert (await scraper.fetch_device_list()).success is False
