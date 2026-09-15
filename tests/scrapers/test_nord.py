from datetime import datetime

import pytest

from tests.support import _stub_fetch


def _nord_page(heading, files, statement="", history=None, title="Downloads"):
    """A downloads page's OS accordion, as nordkeyboards.com writes it."""
    history_link = f'<p><a href="{history}">Update history</a></p>' if history else ""
    return (
        f'<html><body><main><h1>{title}</h1><div class="StreamField">'
        '<div class="Accordion-module-scss-module__Rd951a__Accordion"><div class="Accordion-module-scss-module__Rd951a__Accordion__Container">'
        f'<div class="Accordion-module-scss-module__Rd951a__Accordion__Wrapper"><h2 class="Accordion__Title">{heading}</h2>'
        f'<div class="Accordion__Text"><div class="RawHtml">{files}{history_link}</div></div></div>'
        f'<div class="Accordion__Content"><div class="RawHtml">{statement}</div></div></div></div>'
        '<div class="Accordion-module-scss-module__Rd951a__Accordion"><div class="Accordion-module-scss-module__Rd951a__Accordion__Container">'
        '<h2>User manual</h2><p><a href="/wt/documents/9/Nord%20Manual%20v2.1.pdf">Nord Manual v2.1</a></p></div></div>'
        "</div></main></body></html>"
    )


def _nord_file(label, date, name):
    return f'<p>{label} ({date})<br/><a href="/wt/documents/1/{name}">{name}</a></p>' if date else \
        f'<p>{label}<br/><a href="/wt/documents/1/{name}">{name}</a></p>'


NORD_GRAND_2 = _nord_page(
    "OS Update",
    _nord_file("macOS", "2025-04-10", "Update Nord Grand 2 OS v1.22") + _nord_file("Windows", "2025-04-10", "Update Nord Grand 2 OS v1.22"),
    "<p><b>Nord Grand 2 OS Update</b><br/>Latest version: 1.22<br/>Released: 2025-04-10</p>",
    title="Nord Grand",
)

NORD_ELECTRO_3 = _nord_page(
    "OS Update",
    "<p><b>Nord Electro 3 61 &amp; 73 OS Update</b></p>"
    + _nord_file("Download for Mac OSX", "2018-04-19", "Update Nord Electro 3 OS v3.14")
    + "<p><b>Nord Electro 3 HP OS Update</b></p>"
    + _nord_file("Download for Mac OSX", "2018-04-20", "Update Nord Electro 3HP OS v3.16"),
    "<p><b>Nord Electro 3 OS Update</b><br/>Latest version 61/73: 3.14<br/>Latest version HP: 3.16<br/>Released: 2018-04-19</p>",
)

NORD_LEAD_3 = _nord_page(
    "Nord Lead 3 OS (legacy)",
    _nord_file("Download for Mac OS (legacy)", None, "Nord Lead 3 OS v1.20 Update")
    + _nord_file("Download for Windows (legacy)", None, "Nord Lead 3 OS v1.20 Update (SMF)"),
)

NORD_LEAD_2X = _nord_page("Nord Lead 2X OS", "<p>No updates available.<br/></p>", "<p>Final version: 1.00<br/>Released: 2003-01-01</p>")

NORD_LEAD_2 = _nord_page(
    "Nord Lead 2 OS",
    "<p><b>The final version of the Nord Lead 2 operating system is v1.06.</b><br/>This version was available as an "
    "EEPROM chip replacement but is now <b>out of stock</b>.</p><p>Final version: 1.06<br/>Released: 2003-01-01</p>",
)

NORD_LEAD = _nord_page("Nord Lead OS", "<p><b>The final version of the Nord Lead 1 operating system is v2.70.</b></p>",
                       "<p>Latest version: 2.70<br/>Released: 2002-11-05</p>")

NORD_MODULAR = _nord_page(
    "Nord Modular OS", _nord_file("Download for Mac OS", "2007-06-26", "Nord Modular OS v3.03b Update"),
    "<p><b>Nord Modular OS</b><br/>Latest version: 3.03<br/>Released: 2007-06-26</p><p><b>Important notice</b></p>",
)

NORD_WAVE_2 = _nord_page(
    "OS Update", _nord_file("macOS", "2024-05-21", "Update Nord Wave 2 OS v1.24"),
    "<p><b>Nord Wave 2 OS Update</b><br/>Latest version: 1.24<br/>Released: 2024-05-21</p>",
    history="/update-history/nord-wave-2-update-history/",
)

NORD_STAGE_2 = _nord_page(
    "OS Update", _nord_file("macOS", "2019-02-12", "Update Nord Stage 2 OS v3.00"),
    "<p><b>Nord Stage 2 OS Update</b><br/>Latest version: 3.0<br/>Released: 2019-02-12</p>",
)

NORD_WAVE_2_HISTORY = (
    "<html><body><main><h1>Nord Wave 2 - Update History</h1><div class=\"RawHtml\">"
    "<h4>OS v1.24 (2024-05-11)</h4><ul><li>Fixed arpeggiator sync</li></ul>"
    "<h4>v1.14 (2023-09-15)</h4><ul><li>Program format was updated to v3.08</li><li>Synth Preset format was updated to v2.06</li></ul>"
    "<h4>v1.0</h4><ul><li>First release</li></ul>"
    "</div></main></body></html>"
)


def test_nord_names_the_product_from_its_os_statement_not_the_page_heading():
    """The Nord Grand 2 page's heading says "Nord Grand", which is a different, legacy product."""
    from src.scrapers.plugins.nord import NordScraper

    [release] = NordScraper()._parse_downloads(NORD_GRAND_2)

    assert (release.name, release.version, release.released) == ("Nord Grand 2", "1.22", datetime(2025, 4, 10))


def test_nord_reads_each_model_from_its_file_when_one_statement_covers_two():
    from src.scrapers.plugins.nord import NordScraper

    releases = NordScraper()._parse_downloads(NORD_ELECTRO_3)

    assert [(r.name, r.version, r.released) for r in releases] == [
        ("Nord Electro 3", "3.14", datetime(2018, 4, 19)), ("Nord Electro 3HP", "3.16", datetime(2018, 4, 20)),
    ]


def test_nord_reads_a_page_without_a_statement_from_its_files_and_invents_no_date():
    from src.scrapers.plugins.nord import NordScraper

    releases = NordScraper()._parse_downloads(NORD_LEAD_3)

    assert [(r.name, r.version, r.released) for r in releases] == [("Nord Lead 3", "1.20", None)]


def test_nord_leaves_a_final_version_dated_new_years_day_undated():
    """Nord Lead 2X ("No updates available") and Lead 2 ("out of stock") both say "Released: 2003-01-01"."""
    from src.scrapers.plugins.nord import NordScraper

    scraper = NordScraper()

    assert [(r.name, r.version, r.released) for r in scraper._parse_downloads(NORD_LEAD_2X)] == [("Nord Lead 2X", "1.00", None)]
    assert [(r.name, r.version, r.released) for r in scraper._parse_downloads(NORD_LEAD_2)] == [("Nord Lead 2", "1.06", None)]
    # A latest version keeps its real date.
    assert [(r.name, r.released) for r in scraper._parse_downloads(NORD_LEAD)] == [("Nord Lead", datetime(2002, 11, 5))]


def test_nord_names_a_statement_without_update_or_without_a_name():
    """ "Nord Modular OS" in bold; Nord Lead 2X names itself only in the accordion heading."""
    from src.scrapers.plugins.nord import NordScraper

    scraper = NordScraper()

    assert [(r.name, r.version) for r in scraper._parse_downloads(NORD_MODULAR)] == [("Nord Modular", "3.03")]
    assert [r.name for r in scraper._parse_downloads(NORD_LEAD_2X)] == ["Nord Lead 2X"]


def test_nord_pads_a_one_digit_minor_so_a_release_is_stored_once():
    from src.scrapers.plugins.nord import NordScraper

    [release] = NordScraper()._parse_downloads(NORD_STAGE_2)

    assert release.version == "3.00"


def test_nord_history_reads_release_headings_but_not_versions_in_the_notes():
    from src.scrapers.plugins.nord import NordScraper

    history = NordScraper()._parse_history(NORD_WAVE_2_HISTORY)

    assert [(fw.version, fw.release_date) for fw in history] == [
        ("1.24", datetime(2024, 5, 11)), ("1.14", datetime(2023, 9, 15)), ("1.00", None),
    ]
    assert history[1].changelog == "Program format was updated to v3.08 Synth Preset format was updated to v2.06"


@pytest.mark.asyncio
async def test_nord_lists_current_and_legacy_products_and_prefers_the_history_date():
    """Nord Wave 2's statement says 1.24 shipped 2024-05-21; the history, the release record, says 2024-05-11."""
    from src.scrapers.plugins.nord import NordScraper as N

    scraper = N()
    listing = (
        '<html><body><h2>Current products</h2><a href="/products/nord-wave-2/downloads?scrollToTabs=1">Wave 2</a>'
        '<a href="/products/nord-grand-2/downloads?scrollToTabs=1">Grand 2</a><a href="/products/nord-wave-2/">Overview</a>'
        '<h2>Legacy products</h2><a href="/legacy-products/nord-lead-2x/downloads?scrollToTabs=1">Lead 2X</a></body></html>'
    )
    asked = _stub_fetch(scraper, {
        N.DOWNLOADS_URL: listing,
        N.BASE_URL + "/products/nord-wave-2/downloads": NORD_WAVE_2,
        N.BASE_URL + "/products/nord-grand-2/downloads": NORD_GRAND_2,
        N.BASE_URL + "/legacy-products/nord-lead-2x/downloads": NORD_LEAD_2X,
        N.BASE_URL + "/update-history/nord-wave-2-update-history/": NORD_WAVE_2_HISTORY,
    })

    devices = {d.name: d for d in (await scraper.fetch_device_list()).devices}
    wave = await scraper.fetch_firmware_versions("Nord Wave 2", devices["Nord Wave 2"].firmware_page_url)

    assert sorted(devices) == ["Nord Grand 2", "Nord Lead 2X", "Nord Wave 2"]
    assert {d.category for d in devices.values()} == {"synthesizer"}
    assert [(fw.version, fw.release_date) for fw in wave.firmware_versions][0] == ("1.24", datetime(2024, 5, 11))
    assert len(asked) == len(set(asked)) == 5


@pytest.mark.asyncio
async def test_nord_fails_loudly_without_the_downloads_listing():
    from src.scrapers.plugins.nord import NordScraper as N

    scraper = N()
    _stub_fetch(scraper, {})

    assert (await scraper.fetch_device_list()).success is False
