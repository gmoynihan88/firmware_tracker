import pytest

from tests.support import _stub_fetch


def _waves_post(date, *lines, title=None, old_layout=False):
    """One post. The oldest tabs write the date as a bold paragraph rather than a heading."""
    date_html = (f'<p class="waves-p"><strong>{date}</strong></p>' if old_layout
                 else f'<p class="waves-h4">{date}</p>')
    title_html = f'<p class="waves-p pt-5"><strong>{title}</strong></p>' if title else ""
    return (f'<div>{date_html}{title_html}<ul class="waves-ul pb-7">'
            + "".join(f"<li>{line}</li>" for line in lines) + "</ul></div>")


def _waves_page(*posts):
    return '<html><body><section class="hidden" data-tabs="" id="ctnt-v17">' + "".join(posts) + "</section></body></html>"


WAVES_PAGE = _waves_page(
    _waves_post("August 2, 2026", "<strong>Waves Central v17.0.4</strong> is now available with the following updates: uninstall single products"),
    _waves_post("June 23, 2026", "<strong>New Features &amp; Improvements in Waves V17</strong><ul><li>New: Preset Menu.</li></ul>",
                title="All Waves Plugins: Across-the-board software update to V17"),
    _waves_post("December 15, 2025", "New: Morphoder redesign.", title="All Waves Plugins: Across-the-board software update to V16"),
    _waves_post("June 23, 2025", "New: resizable interfaces.", title="All Waves Plugins: Across-the-board software update to V16"),
    '<div><p class="waves-h4">January 1, 2023</p><ul class="waves-ul">'
    "<li><strong>Waves Central v13.5.3</strong> is now available with the following updates:</li>"
    '<ul class="waves-ul"><li>License activation on exFAT drives.</li></ul>'
    "<li><strong>New Update:</strong> StudioRack hosts VST3 plugins.</li></ul></div>",
    _waves_post("October 11th, 2021", "OS and DAW Compatibility:", title="All Waves Plugins: Across-the-board software update to V13"),
    _waves_post("December 20th, 2020", "New: SoundGrid QRec v12.2.0.155",
                title="All Waves SoundGrid applications, firmware and drivers: Across-the-board software update to V12:"),
    _waves_post("November 2, 2020", "SuperRack v12.2 now requires Waves Central 12.0.7 or later"),
    _waves_post("July 20, 2017", "All Waves plugins: Across-the-board software update to version 9.92.",
                "Waves Central 1.3.7.8: Bug fixes, stability improvements", old_layout=True),
    _waves_post("April 19th, 2017", "Version 9.91 across-the-board update of all Waves plugins.",
                "H-EQ: New H-EQ Lite components.", old_layout=True),
)


WAVES_CHALLENGE = '<html><head><script src="/_Incapsula_Resource?SWJIYLWA=5074a744"></script><body></body></html>'


def test_waves_dates_a_generation_by_its_first_post_and_skips_soundgrid():
    """V16 shipped in June 2025 and was updated in December; SoundGrid's V12 is not a plug-in generation."""
    from src.scrapers.plugins.waves import WavesScraper

    plugins = WavesScraper()._parse_release_notes(WAVES_PAGE)["Waves Plugins"]

    assert [(fw.version, fw.release_date.date().isoformat()) for fw in plugins] == [
        ("17", "2026-06-23"), ("16", "2025-06-23"), ("13", "2021-10-11"), ("9.92", "2017-07-20"), ("9.91", "2017-04-19"),
    ]


def test_waves_generation_notes_run_from_the_generation_line_to_the_next_post():
    from src.scrapers.plugins.waves import WavesScraper

    plugins = {fw.version: fw for fw in WavesScraper()._parse_release_notes(WAVES_PAGE)["Waves Plugins"]}

    assert plugins["17"].changelog.splitlines() == [
        "All Waves Plugins: Across-the-board software update to V17",
        "New Features & Improvements in Waves V17 New: Preset Menu.",
    ]
    assert plugins["9.91"].changelog.splitlines()[-1] == "H-EQ: New H-EQ Lite components."


def test_waves_reads_central_releases_but_not_lines_that_mention_central():
    """ "SuperRack ... requires Waves Central 12.0.7" is not a release; a sub-list after its bullet is its notes."""
    from src.scrapers.plugins.waves import WavesScraper

    central = {fw.version: fw for fw in WavesScraper()._parse_release_notes(WAVES_PAGE)["Waves Central"]}

    assert list(central) == ["17.0.4", "13.5.3", "1.3.7.8"]
    assert central["13.5.3"].changelog == (
        "Waves Central v13.5.3 is now available with the following updates: License activation on exFAT drives."
    )


@pytest.mark.asyncio
async def test_waves_uses_the_browser_when_the_plain_fetch_gets_a_challenge():
    from src.scrapers.plugins.waves import WavesScraper as W

    scraper = W()
    plain = _stub_fetch(scraper, {W.RELEASE_NOTES_URL: WAVES_CHALLENGE})
    browser = _stub_fetch(scraper, {W.RELEASE_NOTES_URL: WAVES_PAGE}, attr="fetch_page_js")

    devices = {d.name: d.category for d in (await scraper.fetch_device_list()).devices}
    await scraper.fetch_firmware_versions("Waves Central", W.RELEASE_NOTES_URL)

    assert plain == browser == [W.RELEASE_NOTES_URL]
    assert devices == {"Waves Plugins": "vst_plugin", "Waves Central": "vst_plugin"}


@pytest.mark.asyncio
async def test_waves_fails_loudly_without_plugin_generations():
    from src.scrapers.plugins.waves import WavesScraper as W

    scraper = W()
    _stub_fetch(scraper, {W.RELEASE_NOTES_URL: _waves_page(_waves_post("August 2, 2026", "Waves Central v17.0.4 is now available"))})
    _stub_fetch(scraper, {}, attr="fetch_page_js")

    assert (await scraper.fetch_device_list()).success is False
