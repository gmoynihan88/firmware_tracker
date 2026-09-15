import pytest

from tests.support import _stub_fetch


def _st_log(*entries):
    """The release log: a bold paragraph per release, then its date, then notes.

    Each entry is (heading, date paragraph or None, notes markup).
    """
    body = "".join(
        f"<p><strong>{heading}</strong></p>"
        + (f"<p>{date}</p>" if date is not None else "")
        + notes
        for heading, date, notes in entries
    )
    return f'<main><section class="block block-freepage black"><h1>Release Log</h1>{body}</section></main>'


def test_soundtoys_reads_dates_written_every_way_the_log_writes_them():
    """A pattern for "July 7, 2026" alone left four dated releases undated."""
    from src.scrapers.plugins.soundtoys import SoundtoysScraper

    versions = SoundtoysScraper()._parse_release_log(_st_log(
        ("Soundtoys 5.5.5 Update", "July 7, 2026", "<ul><li>Fixes PanMan</li></ul>"),
        ("SpaceBlender Software Update (5.5.1.18546)", "June 05, 2025", ""),
        ("5.4.3 Update", "June 20th, 2024<b><br/></b>", "<ul><li>SuperPlate fix</li></ul>"),
        ("5.3.6 Update", "October, 20, 2021", "<ul><li>Fix</li></ul>"),
        ("Product Update 5.0.3.11645 (Mac only)", "<em>June 2, 2016:</em>", "<p>Fixes:</p>"),
    ))

    assert [(fw.version, fw.release_date.date().isoformat()) for fw in versions] == [
        ("5.5.5", "2026-07-07"),
        ("5.5.1", "2025-06-05"),
        ("5.4.3", "2024-06-20"),
        ("5.3.6", "2021-10-20"),
        ("5.0.3", "2016-06-02"),
    ]


def test_soundtoys_keeps_the_version_and_drops_the_build():
    """The fourth number differs between the Mac and PC builds of one release."""
    from src.scrapers.plugins.soundtoys import SoundtoysScraper

    versions = SoundtoysScraper()._parse_release_log(_st_log(
        ("Maintenance Update 5.2.4.13665 (Mac) and 5.2.4.13670 (PC)", "June 13, 2018", ""),
        ("5.4 Update", "May 16, 2023", ""),
    ))

    assert [fw.version for fw in versions] == ["5.4", "5.2.4"]


def test_soundtoys_dates_a_repeated_version_by_its_first_release():
    """5.0.1 shipped for Mac and PC, then again for PC alone, further up the log."""
    from src.scrapers.plugins.soundtoys import SoundtoysScraper

    free = "<p><em>(Free update for all version 5 product owners)</em></p>"
    versions = SoundtoysScraper()._parse_release_log(_st_log(
        ("Maintenance Update 5.0.1.10839 (PC)", None,
         free + "<p><em>October 30, 2015</em></p><ul><li>PC rebuild</li></ul>"),
        ("Maintenance Update 5.0.1.10798 (Mac &amp; PC)", None,
         free + '<p style="text-align: left;"><em>October 13, 2015</em></p><ul><li>First fix</li></ul>'),
    ))

    assert len(versions) == 1
    assert versions[0].release_date.date().isoformat() == "2015-10-13"
    assert versions[0].changelog.splitlines() == [
        "(Free update for all version 5 product owners)", "- PC rebuild",
        "(Free update for all version 5 product owners)", "- First fix",
    ]


def test_soundtoys_finds_the_date_after_a_note_that_opens_the_release():
    """5.2.4 opens with a note that itself mentions a date, then gives its own."""
    from src.scrapers.plugins.soundtoys import SoundtoysScraper

    versions = SoundtoysScraper()._parse_release_log(_st_log(
        ("Maintenance Update 5.2.4.13665 (Mac) and 5.2.4.13670 (PC)", None,
         "<p><em>NOTE: This update is effectively the same as 5.2.3, recalled on June 5, 2018.</em></p>"
         "<p><em>June 13, 2018</em></p><ul><li>Little Plate now included</li></ul>"),
    ))

    assert versions[0].release_date.date().isoformat() == "2018-06-13"
    assert versions[0].changelog.splitlines()[0].startswith("NOTE: This update")


def test_soundtoys_leaves_an_undated_release_undated_and_skips_what_is_not_one():
    """5.5.2 opens with "Features:"; a date further into its notes is not its date."""
    from src.scrapers.plugins.soundtoys import SoundtoysScraper

    versions = SoundtoysScraper()._parse_release_log(_st_log(
        ("Soundtoys 5.5.2 Update", None,
         "<p>Features:</p><ul><li>SpaceBlender in Effect Rack</li></ul><p>October 1, 2025</p>"),
        ("Outer Limits Preset Expander", "<em>October 31, 2017</em>", "<p>New presets</p>"),
        ("5.1.0 Update", "<strong></strong><em>September 28, 2016</em>", "<ul><li>Mac fix</li></ul>"),
    ))

    assert [(fw.version, fw.release_date) for fw in versions][0] == ("5.5.2", None)
    assert [fw.version for fw in versions] == ["5.5.2", "5.1.0"]
    assert "October 1, 2025" in versions[0].changelog
    # An empty <strong> beside the date does not make the date paragraph a heading.
    assert versions[1].release_date.date().isoformat() == "2016-09-28"


@pytest.mark.asyncio
async def test_soundtoys_lists_the_suite_as_one_device_from_one_fetch():
    from src.scrapers.plugins.soundtoys import SoundtoysScraper as ST

    scraper = ST()
    asked = _stub_fetch(scraper, {ST.RELEASE_LOG_URL: _st_log(
        ("Soundtoys 5.5.5 Update", "July 7, 2026", "<ul><li>Fix</li></ul>"),
        ("Soundtoys 5.5.4 Update", "November 25, 2025", "<ul><li>Fix</li></ul>"),
    )})

    devices = (await scraper.fetch_device_list()).devices
    result = await scraper.fetch_firmware_versions(devices[0].name, devices[0].firmware_page_url)

    assert asked == [ST.RELEASE_LOG_URL]
    assert [(d.name, d.category) for d in devices] == [("Soundtoys 5", "vst_plugin")]
    assert [fw.version for fw in result.firmware_versions] == ["5.5.5", "5.5.4"]


@pytest.mark.asyncio
async def test_soundtoys_fails_loudly_without_the_release_log():
    from src.scrapers.plugins.soundtoys import SoundtoysScraper as ST

    scraper = ST()
    _stub_fetch(scraper, {ST.RELEASE_LOG_URL: "<main><p>Page not found</p></main>"})

    assert (await scraper.fetch_device_list()).success is False
