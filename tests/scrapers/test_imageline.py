import pytest

from tests.support import _stub_fetch


def _fl_page(*sections):
    """The What's New page: headings with dates in brackets, notes beside them."""
    return "<html><body><h1>What's New?</h1>" + "".join(sections) + "</body></html>"


def test_fl_studio_skips_prereleases_and_reads_qualified_headings():
    """RC, beta, "Rlease Candidate" and "not released" are not releases; "build 33" and "x64" are."""
    from src.scrapers.plugins.imageline import ImageLineScraper

    versions = ImageLineScraper()._parse_whats_new(_fl_page(
        "<h3>26.1.6 (2026/09/02)</h3><p>Changes</p>",
        "<h3>26.1 RC1 (2026/06/25)</h3><p>rc</p>",
        "<h3>26.1 beta 11 (2026/06/17)</h3><p>beta</p>",
        "<h3>FL Studio 25 Beta 3 (2025/March/28)</h3>",
        "<h2>20.9.2 macOS bug fix update (2022 / Aug / 18)</h2><p>mac</p>",
        "<h3>20.8 Rlease Candidate 6 (2020 / Dec / 07)</h3><p>rc</p>",
        "<h3>12.4.2 build 33 (03 / Apr / 2017)</h3><p>build</p>",
        "<h3>11.1 x64 (14 / Jul / 2014)</h3><p>x64</p>",
        "<h3>1.2.13 (not released)</h3>",
    ))

    assert [fw.version for fw in versions] == ["26.1.6", "20.9.2", "12.4.2", "11.1"]


def test_fl_studio_reads_every_date_shape():
    from src.scrapers.plugins.imageline import ImageLineScraper

    parse = ImageLineScraper._date
    assert {raw: (parse(raw).date().isoformat() if parse(raw) else None) for raw in (
        "2026/09/02", "2023 / Aug / 29", "03 / Apr / 2017", "9 December 2019",
        "22 / Feb / ruary 2019", "21 / March / 98 ", "BETA 2",
    )} == {
        "2026/09/02": "2026-09-02",
        "2023 / Aug / 29": "2023-08-29",
        "03 / Apr / 2017": "2017-04-03",
        "9 December 2019": "2019-12-09",
        "22 / Feb / ruary 2019": "2019-02-22",
        "21 / March / 98 ": "1998-03-21",
        "BETA 2": None,
    }


def test_fl_studio_2024_releases_are_version_24():
    """Stored as "2024.2.2" it would sort above 26.1.6 and become the latest version."""
    from src.scrapers.plugins.imageline import ImageLineScraper

    versions = ImageLineScraper()._parse_whats_new(_fl_page(
        "<h3>26.1.6 (2026/09/02)</h3><p>x</p>",
        "<h3>24.2.99 Beta 9 (2025/ June / 28)</h3><p>beta toward the next major</p>",
        "<h3>2024.2.2 (2025/ Feb / 03)</h3><p>x</p>",
        "<h3>2024.1.1b (2024 / Jul / 10)</h3><p>x</p>",
    ))

    assert [(fw.version, fw.release_date.date().isoformat()) for fw in versions] == [
        ("26.1.6", "2026-09-02"), ("24.2.2", "2025-02-03"), ("24.1.1b", "2024-07-10"),
    ]


def test_fl_studio_reads_notes_beside_a_heading_inside_a_list():
    """From 20.x back each release sits in a list item, its notes beside the heading."""
    from src.scrapers.plugins.imageline import ImageLineScraper

    versions = ImageLineScraper()._parse_whats_new(_fl_page(
        "<ul><li>"
        "<h2>20.8 (2020 / Dec / 09)</h2><p><u>Bugfixes</u></p>"
        "<ul><li>10428 Crash report: resizing text</li><li>10415 Mini Piano Roll bar count</li></ul>"
        "<h3>20.8 Rlease Candidate 6 (2020 / Dec / 07)</h3><p>A release-candidate note</p>"
        "</li></ul>"
    ))

    assert [fw.version for fw in versions] == ["20.8"]
    assert versions[0].changelog.splitlines() == [
        "Bugfixes", "- 10428 Crash report: resizing text", "- 10415 Mini Piano Roll bar count",
    ]


def test_fl_studio_dates_a_repeated_version_by_its_first_release():
    from src.scrapers.plugins.imageline import ImageLineScraper

    versions = ImageLineScraper()._parse_whats_new(_fl_page(
        "<h3>20.0.5 (3 October 2018)</h3><p>re-release</p>",
        "<h3>20.0.5 (25 September 2018)</h3><p>first release</p>",
    ))

    assert [(fw.version, fw.release_date.date().isoformat()) for fw in versions] == [("20.0.5", "2018-09-25")]
    assert versions[0].changelog.splitlines() == ["re-release", "first release"]


@pytest.mark.asyncio
async def test_fl_studio_is_one_device_from_one_fetch():
    from src.scrapers.plugins.imageline import ImageLineScraper as IL

    scraper = IL()
    asked = _stub_fetch(scraper, {IL.WHATS_NEW_URL: _fl_page("<h3>26.1.6 (2026/09/02)</h3><p>x</p>")})

    devices = (await scraper.fetch_device_list()).devices
    result = await scraper.fetch_firmware_versions(devices[0].name, devices[0].firmware_page_url)

    assert asked == [IL.WHATS_NEW_URL]
    assert [(d.name, d.category) for d in devices] == [("FL Studio", "vst_plugin")]
    assert [fw.version for fw in result.firmware_versions] == ["26.1.6"]


@pytest.mark.asyncio
async def test_fl_studio_fails_loudly_without_the_page():
    from src.scrapers.plugins.imageline import ImageLineScraper as IL

    scraper = IL()
    _stub_fetch(scraper, {IL.WHATS_NEW_URL: "<html><h1>Not found</h1></html>"})

    assert (await scraper.fetch_device_list()).success is False
