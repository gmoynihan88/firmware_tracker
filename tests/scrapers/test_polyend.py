import pytest

from tests.support import _stub_fetch


def _pe_version(number, title, *notes):
    items = "".join(f'<li aria-level="1">{note}</li>' for note in notes)
    return (
        '<div class="changelog__version">'
        f'<div class="changelog__version__number">\n        {number}       </div>'
        '<div class="changelog__version__wrapper">'
        f'<div class="changelog__version__title">\n        {title}       </div>'
        f'<div class="changelog__version__content"><div class="changelog__version__content"><h3>FIXES</h3><ul>{items}</ul></div></div>'
        "</div></div>"
    )


def _pe_item(file_name, *versions):
    changelog = (
        '<div class="changelog"><h3 class="changelog__title">Changelog</h3>'
        f'<div class="changelog__versions">{"".join(versions)}</div></div>'
    ) if versions else ""
    link = f'<a href="https://polyend.com/wp-content/uploads/{file_name}">Download</a>' if file_name else ""
    return f'<div class="download-item"><div class="download-item__title">Firmware</div>{link}{changelog}</div>'


def _pe_page(heading, *items):
    """A downloads page, with the site menu's own headings above it as the live page has."""
    return (
        '<html><body><nav><h2>Products</h2><h3>Guitar pedals</h3><h3>Synthesizers</h3></nav>'
        f'<main><h1>{heading}</h1><h2>Software</h2>{"".join(items)}<h2>Manuals</h2>'
        '<div class="download-item"><a href="https://polyend.com/wp-content/uploads/Manual_v2.1.pdf">Manual</a></div></main></body></html>'
    )


TRACKER_MINI_CHANGELOG = (
    _pe_version("2.2.1", "Changes from Tracker Mini 2.2 to 2.2.1", "Fixed sample preview"),
    _pe_version("2.2", "Changes from Tracker Mini 2.1 to 2.2", "New display theme"),
)
TRACKER_MINI = _pe_page("Tracker Mini downloads", _pe_item("TrackerMini_2.2.1.ptf.zip", *TRACKER_MINI_CHANGELOG))
TRACKER_MINI_BLACK = _pe_page("Tracker Mini Aluminum (Black) downloads", _pe_item("TrackerMini_2.2.1.ptf.zip", *TRACKER_MINI_CHANGELOG))

PLAY_PLUS = _pe_page("Play+ downloads", _pe_item(
    "PlayPlus_v1.3.0.zip",
    _pe_version("1.3.0", "Changes from Play+ 1.2.0 to 1.3.0", "Perform FX in MIDI tracks"),
    _pe_version("1.0.1 beta", "Changes from Play+ 1.0.0 to 1.0.1 beta", "Beta fixes"),
    _pe_version("1.0.0", "Initial release", "First release"),
))

STEP = _pe_page("Step downloads",
                _pe_item("PolyendStep_1.0.1.pstf_.zip", _pe_version("1.0.1", "Changes from 1.0 to 1.0.1", "Clock fix")),
                _pe_item(None, _pe_version("1.0.1", "Changes from 1.0 to 1.0.1", "Clock fix, as listed under the manual")))

ENDLESS = _pe_page("Endless Downloads", _pe_item(None))

POLYEND_TOOL = _pe_page("Polyend Tool downloads", _pe_item("Polyend_Tool_v1.2.1_macOS.zip",
                                                           _pe_version("1.2.1", "Latest release", "Updates Tracker firmware")))


def test_polyend_reads_each_changelog_version_with_its_notes_and_skips_betas():
    from src.scrapers.plugins.polyend import PolyendScraper

    name, versions = PolyendScraper()._parse_page(PLAY_PLUS)

    assert name == "Play+"
    assert [(fw.version, fw.release_date) for fw in versions] == [("1.3.0", None), ("1.0.0", None)]
    assert versions[0].changelog.splitlines() == ["Changes from Play+ 1.2.0 to 1.3.0", "FIXES", "Perform FX in MIDI tracks"]


def test_polyend_takes_a_version_once_when_a_page_repeats_its_changelog():
    from src.scrapers.plugins.polyend import PolyendScraper

    name, versions = PolyendScraper()._parse_page(STEP)

    assert (name, [fw.version for fw in versions]) == ("Step", ["1.0.1"])
    assert versions[0].changelog.splitlines()[-1] == "Clock fix"  # the firmware item's own entry, not the repeat


def test_polyend_skips_a_page_with_no_changelog():
    from src.scrapers.plugins.polyend import PolyendScraper

    assert PolyendScraper()._parse_page(ENDLESS) is None


@pytest.mark.asyncio
async def test_polyend_collapses_colour_variants_and_leaves_out_the_companion_app():
    """Tracker Mini Aluminum (Black) carries Tracker Mini's changelog; Polyend Tool is an app."""
    from src.scrapers.plugins.polyend import PolyendScraper as P

    scraper = P()
    base = P.BASE_URL + "/downloads/"
    listing = "".join(f'<a href="{base}{slug}-downloads/">{slug}</a>' for slug in
                      ("tracker-mini-aluminum-black", "tracker-mini", "play-plus", "step", "endless", "polyend-tool"))
    asked = _stub_fetch(scraper, {
        P.LISTING_URL: f"<html><body>{listing}<a href='{base}tracker-mini-downloads/'>again</a></body></html>",
        base + "tracker-mini-aluminum-black-downloads/": TRACKER_MINI_BLACK,
        base + "tracker-mini-downloads/": TRACKER_MINI,
        base + "play-plus-downloads/": PLAY_PLUS,
        base + "step-downloads/": STEP,
        base + "endless-downloads/": ENDLESS,
        base + "polyend-tool-downloads/": POLYEND_TOOL,
    })

    devices = {d.name: d for d in (await scraper.fetch_device_list()).devices}
    mini = await scraper.fetch_firmware_versions("Polyend Tracker Mini", devices["Polyend Tracker Mini"].firmware_page_url)

    assert {name: d.category for name, d in devices.items()} == {
        "Polyend Tracker Mini": "synthesizer", "Polyend Play+": "synthesizer", "Polyend Step": "guitar_pedal",
    }
    assert devices["Polyend Tracker Mini"].firmware_page_url == base + "tracker-mini-downloads/"
    assert [fw.version for fw in mini.firmware_versions] == ["2.2.1", "2.2"]
    assert len(asked) == 7


@pytest.mark.asyncio
async def test_polyend_fails_loudly_without_the_downloads_listing():
    from src.scrapers.plugins.polyend import PolyendScraper as P

    scraper = P()
    _stub_fetch(scraper, {})

    assert (await scraper.fetch_device_list()).success is False
