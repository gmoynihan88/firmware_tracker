import asyncio

import pytest


def _ableton_page() -> str:
    return """
    <h2>12.4.5
        Release Notes</h2>
    <div class="release_note_text">
      <h4>August 26, 2026</h4>
      <h3>New Features and Improvements</h3>
      <ul><li>Added Control Surface support, replacing the behaviour from May 5, 2025.</li></ul>
    </div>

    <h2>12.0.20
        Release Notes</h2>
    <div class="release_note_text">
      <h4>Aug 6, 2024</h4>
      <ul><li>No Live specific release notes.</li></ul>
    </div>

    <h2>11.3.42
        Release Notes</h2>
    <div class="release_note_text">
      <h3>Move Control Surface Updates</h3>
      <p>April 14, 2025</p>
      <ul><li>A notification is now shown when steps are transposed.</li></ul>
    </div>

    <h2>11.0.12
        Release Notes</h2>
    <div class="release_note_text">
      <h3>Bugfixes:</h3>
      <ul><li>Fixed an issue reported back in January 3, 2021 by several users.</li></ul>
    </div>

    <h2>12.5
        Coming Soon</h2>
    <p>Not a release block, so not a release.</p>
    """


def test_ableton_reads_the_date_from_each_of_its_three_positions():
    """First child, after a section heading, and abbreviated."""
    from src.scrapers.plugins.ableton import AbletonScraper

    by_version = {fw.version: fw for fw in AbletonScraper()._parse_releases(_ableton_page())}

    assert by_version["12.4.5"].release_date.strftime("%Y-%m-%d") == "2026-08-26"
    assert by_version["11.3.42"].release_date.strftime("%Y-%m-%d") == "2025-04-14"
    # "Aug 6, 2024" -- requiring the long spelling silently dropped this one.
    assert by_version["12.0.20"].release_date.strftime("%Y-%m-%d") == "2024-08-06"


def test_ableton_leaves_an_undated_release_undated():
    """11.0.12 opens straight into "Bugfixes:" and carries no date on the page.

    Its changelog mentions January 3, 2021, which is a date inside prose about an
    issue rather than the release's own. Taking it would be the fabrication the whole
    project is arranged against, and it is the reason the date is matched against a
    whole element rather than searched for.
    """
    from src.scrapers.plugins.ableton import AbletonScraper

    by_version = {fw.version: fw for fw in AbletonScraper()._parse_releases(_ableton_page())}

    assert by_version["11.0.12"].release_date is None
    assert "January 3, 2021" in by_version["11.0.12"].changelog


def test_ableton_does_not_take_a_date_from_the_changelog_of_a_dated_release():
    """12.4.5's notes mention May 5, 2025; its release date is August 26, 2026."""
    from src.scrapers.plugins.ableton import AbletonScraper

    by_version = {fw.version: fw for fw in AbletonScraper()._parse_releases(_ableton_page())}

    assert by_version["12.4.5"].release_date.year == 2026


def test_ableton_skips_a_version_heading_with_no_notes_under_it():
    """"12.5 Coming Soon" is navigation, not a release."""
    from src.scrapers.plugins.ableton import AbletonScraper

    versions = {fw.version for fw in AbletonScraper()._parse_releases(_ableton_page())}

    assert "12.5" not in versions
    assert versions == {"12.4.5", "12.0.20", "11.3.42", "11.0.12"}


def test_ableton_tracks_a_major_version_as_its_own_product():
    """Following Steinberg's Cubase 12 and Cubase 13.

    One "Ableton Live" row would have 12.4.5 and 11.3.43 competing to be latest, and
    the newer always wins — telling a Live 11 owner they are behind by a major they
    have not bought.
    """
    import asyncio

    from src.scrapers.plugins.ableton import AbletonScraper

    devices = asyncio.run(AbletonScraper().fetch_device_list())
    names = [d.name for d in devices.devices]

    assert names[:2] == ["Live 12", "Live 11"]
    assert "Push" in names, "Push versions itself separately and belongs here too"
    assert all("release-notes" in d.firmware_page_url for d in devices.devices)


@pytest.mark.asyncio
async def test_ableton_fails_when_a_release_notes_page_is_unreachable():
    """An empty success would claim Ableton shipped nothing for that major."""
    from src.scrapers.plugins.ableton import AbletonScraper

    scraper = AbletonScraper()

    async def no_response(url, **kwargs):
        return None

    scraper.fetch_page = no_response
    result = await scraper.fetch_firmware_versions("Live 12", "https://x/")

    assert result.success is False


def _ableton_push_page() -> str:
    """Push's layout: no release_note_text wrapper, date in the p below the heading."""
    return """
    <h1>Push 2.4.5 with Live 12.4.5</h1>
    <p>August 26, 2026</p>
    <h2>New Features and Improvements</h2>
    <h3>Max for Live</h3>
    <ul><li>Added Control Surface support.</li></ul>
    <h2>Push 2.4.3 with Live 12.4.3</h2>
    <p>July 14, 2026</p>
    <h3>Bugfixes</h3>
    <ul><li>Fixed an issue introduced in 12.4.2.</li></ul>
    """


def test_ableton_push_stores_the_device_version_not_the_application_version():
    """"Push 2.4.3 with Live 12.4.3" states both, and only one is the firmware.

    2.4.3 is what a Push reports about itself; 12.4.3 belongs to the application it
    shipped alongside. The two move together, which is what would make taking the
    wrong one invisible.
    """
    from src.scrapers.plugins.ableton import AbletonScraper

    versions = AbletonScraper()._parse_push_releases(_ableton_push_page())

    assert [fw.version for fw in versions] == ["2.4.5", "2.4.3"]
    assert "12.4.5" not in {fw.version for fw in versions}


def test_ableton_push_reads_the_date_below_the_heading():
    """Push has no release_note_text wrapper, so the Live parser finds nothing here."""
    from src.scrapers.plugins.ableton import AbletonScraper

    scraper = AbletonScraper()
    push = scraper._parse_push_releases(_ableton_push_page())

    assert push[0].release_date.strftime("%Y-%m-%d") == "2026-08-26"
    assert push[1].release_date.strftime("%Y-%m-%d") == "2026-07-14"
    # The Live parser must not silently half-work on this page.
    assert scraper._parse_releases(_ableton_push_page()) == []


def test_ableton_push_changelog_stops_at_the_next_release():
    """Without a wrapper the notes are gathered by walking siblings."""
    from src.scrapers.plugins.ableton import AbletonScraper

    versions = AbletonScraper()._parse_push_releases(_ableton_push_page())
    newest = versions[0]

    assert "Added Control Surface support" in newest.changelog
    assert "Fixed an issue" not in newest.changelog, "ran into the next release"


@pytest.mark.asyncio
async def test_ableton_lists_push_as_hardware():
    """Live is software; Push is a thing on a desk."""
    from src.scrapers.plugins.ableton import AbletonScraper

    devices = await AbletonScraper().fetch_device_list()
    by_name = {d.name: d.category for d in devices.devices}

    assert by_name["Push"] == "midi_controller"
    assert by_name["Live 12"] == "vst_plugin"
