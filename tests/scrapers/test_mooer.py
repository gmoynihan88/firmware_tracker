from datetime import datetime

import pytest

from tests.support import _stub_fetch


def _card(header, *groups):
    body = "".join(
        f'<div class="note-group">\n<p class="note-subtitle">{subtitle}</p>\n<ul class="bullet-list">\n'
        + "".join(f"<li>{item}</li>\n" for item in items) + "</ul>\n</div>\n"
        for subtitle, items in groups
    )
    return (f'<div class="version-card">\n<p class="version-header">{header}</p>\n'
            f'<div class="version-body">\n{body}</div>\n</div>\n')


def _page(title, *cards):
    return (
        '<html><body><div class="main"><div><h1 class="e_h1-12 s_subtitle">\n    ' + title + "\n</h1></div>"
        '<p class="e_text-4 s_title">Creation time</p><P class="e_timeFormat-6 s_title">2026-09-01 18:31</P>'
        '<div class="cbox-7-1 p_item"><div class="e_richText-10 s_title clearfix"><div class="ge-firmware-update">'
        + "".join(cards) + "</div></div></div></div></body></html>"
    )


GE1000 = _page(
    "GE1000",
    _card("MOOER Cloud Mobile App V1.7.0 Update (2026.8.31)", ("New Features", ["Pan control for each of the 6 song stems"])),
    _card("APP V3.1.1 Update (2026.7.28)", ("Improvements", ["Optimized native loading performance for NAM A2 Lite models."])),
    _card("GE1000 V3.1.0 Update (2026.7.15)",
          ("Added", ["Added native support for NAM A2 Lite models."]), ("Fixed", ["Fixed an occasional freeze."])),
    _card("GE1000 V3.0.5 Update (Sept 5, 2025)", ("Fixed", ["Fixed USB recording noise issue."])),
    _card("GE1000 V3.0.5 Update", ("Fixed", ["Fixed USB recording noise issue, as first announced."])),
    _card("GE1000 V2.5.0 Update (April, 2024)", ("GE1000 Firmware - Function Additions", ["Added Sub Patch function."])),
)
GE150 = _page(
    "GE150 Plus/Pro/Max",
    _card("GE150 Plus/Pro/Max Firmware Update (2026.8)",
          ("GE150 Plus V2.1.3", ["Added support for converting and importing NAM A2 models.", "Fixed several known bugs."]),
          ("GE150 Max V2.1.6", ["Added support for converting and importing NAM A2 models."]),
          ("Update Instructions", ["Back up your presets first."])),
    _card("GE150 Max V2.1.5 Update (2026.4.23)", ("Added", ["Added NAM import feature in MOOER Studio."])),
    _card("GE150 Plus/Pro V2.1.2 Update (2026.4.23)", ("Added", ["Added NAM import feature in MOOER Studio."])),
    _card("V2.1.3 Update (2026.1.16)", ("Improvements", ["Optimized charge and discharge detection."])),
)
GE300_LITE = _page(
    "GE300 Lite",
    _card("GE300 Lite Firmware Update V5.0.3 (2026.8.4)", ("What's New", ["Added support for NAM A2 models."])),
    _card("GE300 Lite Firmware v1.0.0", ("Update Procedure", ["Please back up the presets before firmware update."])),
)
GE100_PRO = _page(
    "GE100 Pro",
    _card("MS_For_GE100_Pro_V1.3.3 (2026.8.20)", ("Improvement", ["Expression pedal fix."])),
)
GE250_LEGACY = (
    '<html><body><h1 class="e_h1-12 s_subtitle">GE250 Downloads</h1>'
    "<p><strong>GE250 Firmware V2.0.6 (2021.11.01)</strong> In this new firmware version for GE250...</p></body></html>"
)

B = "https://www.mooeraudio.com"
INDEX_1 = (
    '<html><body><a href="/Downloads_xq/4.html">GE1000</a><a href="/Downloads_xq/4.html">GE1000</a>'
    '<a href="/Downloads_xq/12.html">GE100 Pro</a><a href="https://www.mooeraudio.com/companyfile/Downloads-1">Downloads</a>'
    '<div class="p_page"><a class="page_a page_num current" href="javascript:;">1</a>'
    '<a class="page_a page_num" href="/Downloads/p-8-8.html">2</a></div></body></html>'
)
INDEX_2 = (
    '<html><body><a href="/Downloads_xq/6.html">GE150</a>'
    '<a href="/companyfile/GE250-Downloads-148.html">GE250</a><a href="/Downloads_xq/4.html">GE1000</a></body></html>'
)


def test_mooer_reads_firmware_cards_and_skips_app_and_editor_cards():
    from src.scrapers.plugins.mooer import MooerScraper

    scraper = MooerScraper()
    ge1000 = scraper._parse_page(GE1000)

    assert list(ge1000) == ["GE1000"]
    assert [r.version for r in ge1000["GE1000"]] == ["3.1.0", "3.0.5", "2.5.0"]
    assert ge1000["GE1000"][0].changelog == "Added\nAdded native support for NAM A2 Lite models.\nFixed\nFixed an occasional freeze."
    assert scraper._parse_page(GE100_PRO) == {}
    assert scraper._parse_page(GE250_LEGACY) == {}


def test_mooer_reads_every_date_shape():
    from src.scrapers.plugins.mooer import MooerScraper

    scraper = MooerScraper()
    ge1000, lite = scraper._parse_page(GE1000)["GE1000"], scraper._parse_page(GE300_LITE)["GE300 Lite"]

    assert [r.release_date for r in ge1000] == [datetime(2026, 7, 15), datetime(2025, 9, 5), datetime(2024, 4, 1)]
    assert [(r.version, r.release_date) for r in lite] == [("5.0.3", datetime(2026, 8, 4)), ("1.0.0", None)]
    assert scraper._parse_date("2025.8") == datetime(2025, 8, 1)


def test_mooer_splits_cards_that_cover_several_models():
    from src.scrapers.plugins.mooer import MooerScraper

    releases = MooerScraper()._parse_page(GE150)

    assert {model: [(r.version, r.release_date) for r in rs] for model, rs in releases.items()} == {
        "GE150 Plus": [("2.1.3", datetime(2026, 8, 1)), ("2.1.2", datetime(2026, 4, 23))],
        "GE150 Max": [("2.1.6", datetime(2026, 8, 1)), ("2.1.5", datetime(2026, 4, 23))],
        "GE150 Pro": [("2.1.2", datetime(2026, 4, 23))],
    }
    assert releases["GE150 Plus"][0].changelog == (
        "Added support for converting and importing NAM A2 models.\nFixed several known bugs."
    )


@pytest.mark.asyncio
async def test_mooer_walks_every_index_page_to_every_product():
    from src.scrapers.plugins.mooer import MooerScraper as S

    scraper = S()
    asked = _stub_fetch(scraper, {
        S.INDEX_URL: INDEX_1,
        B + "/Downloads/p-8-8.html": INDEX_2,
        B + "/Downloads_xq/4.html": GE1000,
        B + "/Downloads_xq/12.html": GE100_PRO,
        B + "/Downloads_xq/6.html": GE150,
        B + "/companyfile/GE250-Downloads-148.html": GE250_LEGACY,
    })

    devices = {d.name: d.firmware_page_url for d in (await scraper.fetch_device_list()).devices}
    pro = await scraper.fetch_firmware_versions("GE150 Pro", devices["GE150 Pro"])

    assert devices == {"GE1000": B + "/Downloads_xq/4.html", "GE150 Plus": B + "/Downloads_xq/6.html",
                       "GE150 Max": B + "/Downloads_xq/6.html", "GE150 Pro": B + "/Downloads_xq/6.html"}
    assert [r.version for r in pro.firmware_versions] == ["2.1.2"]
    assert len(asked) == 6


@pytest.mark.asyncio
async def test_mooer_fails_loudly_without_the_index():
    from src.scrapers.plugins.mooer import MooerScraper as S

    scraper = S()
    _stub_fetch(scraper, {})

    assert (await scraper.fetch_device_list()).success is False
