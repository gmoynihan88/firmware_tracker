import json
from datetime import datetime

import pytest

from tests.support import _stub_fetch


def _tt_entry(title, date, *notes, post_id=1):
    body = "".join(f"<p>{note}</p>" for note in notes)
    return (
        f'<div class="list-group-item list-group-item-action" href="https://www.toontrack.com/faq/x-{post_id}/" '
        f'title="{title}" rel="bookmark">'
        f'<a class="release-notes-list collapsed" href="#release-note-{post_id}" data-bs-toggle="collapse">{title}</a>'
        f'<div class="collapse" id="release-note-{post_id}"><p class="small-bread">\n        {date}       </p>{body}</div></div>'
    )


def _tt_page(heading, *entries):
    return (
        '<html><body><h1 class="color-text-white">RELEASE NOTES &amp; KNOWN ISSUES.</h1>'
        f'<div id="content" role="main"><ol class="breadcrumb"><li><a href="/release-notes/">Release Notes </a></li>'
        f'<li class="active">{heading}</li></ol><h4 class="mb-3">{heading}</h4>'
        f'<div class="list-group">{"".join(entries)}</div></div></body></html>'
    )


EZBASS = _tt_page(
    "EZbass",
    _tt_entry("Release notes for EZbass 1.3.4", "2026-05-29", "EZbass 1.3.4 is now available.", "<strong>BUG FIXES</strong>", post_id=1),
    _tt_entry("Release notes for Audio Sender 1.0.4", "2020-09-14", "Audio Sender is a separate plug-in.", post_id=2),
    _tt_entry("Release notes for EZbass 1.3.3", "2026-05-19", "Fixes.", post_id=3),
)

EZMIX_3 = _tt_page(
    "EZmix 3",
    _tt_entry("Release notes for EZmix 3.2.2", "2025-12-05", "Fixes.", post_id=1),
    _tt_entry("Release notes for EZmix 3 Core Pack update 3.1.0", "2025-03-25", "New presets.", post_id=2),
    _tt_entry("Release notes for EZmix 3.2.0", "2025-03-25", "New features.", post_id=3),
)

EZDRUMMER_2 = _tt_page(
    "EZdrummer 2",
    _tt_entry("Release notes for EZdrummer 2.2.3", "2022-02-28", "Fixes.", post_id=1),
    _tt_entry("Release notes for EZdrummer 2.1.2", "2016-06-10", "Fixes.", post_id=2),
    # Three releases stamped with the day the notes were imported into the site.
    _tt_entry("Release notes for EZdrummer 2.1.1", "2018-03-16", "Fixes.", post_id=3),
    _tt_entry("Release notes for EZdrummer 2.1.0", "2018-03-16", "Fixes.", post_id=4),
    _tt_entry("Release notes for EZdrummer 2.0.2", "2015-04-23", "Fixes.", post_id=5),
    _tt_entry("Release notes for EZdrummer 2.0.1", "2018-03-16", "Fixes.", post_id=6),
)

SUPERIOR_DRUMMER_2 = _tt_page(
    "Superior Drummer 2",
    _tt_entry("Release notes for Superior Drummer 2.4.4", "2016-06-10", "Fixes.", post_id=1),
    # Dated before the older 2.4.0 and 2.4.2: the one date that contradicts the rest.
    _tt_entry("Release notes for Superior Drummer 2.4.3", "2015-04-30", "Fixes.", post_id=2),
    _tt_entry("Release notes for Superior Drummer 2.4.2", "2015-11-05", "Fixes.", post_id=3),
    _tt_entry("Release notes for Superior Drummer 2.4.0", "2015-10-22", "Fixes.", post_id=4),
    _tt_entry("Release notes for Superior Drummer 2.3.1", "2012-11-26", "Fixes.", post_id=5),
)


def _api(*rows):
    return json.dumps({"vendor": "Toontrack", "plugins": [
        {"name": name, "version": version, "platform": platform, "format": ["VST3", "AU", "AAX"]} for name, version, platform in rows]})


def _dates(versions):
    return [(fw.version, fw.release_date.date().isoformat() if fw.release_date else None) for fw in versions]


def test_toontrack_reads_the_products_own_releases_not_another_plugin_or_a_content_update():
    """The EZbass page carries Audio Sender; EZmix 3 carries a Core Pack update."""
    from src.scrapers.plugins.toontrack import ToontrackScraper

    scraper = ToontrackScraper()

    assert _dates(scraper._parse_page(EZBASS)[1]) == [("1.3.4", "2026-05-29"), ("1.3.3", "2026-05-19")]
    assert _dates(scraper._parse_page(EZMIX_3)[1]) == [("3.2.2", "2025-12-05"), ("3.2.0", "2025-03-25")]


def test_toontrack_names_devices_from_the_page_heading_and_keeps_notes_without_the_date():
    """Entries say "EZdrummer 2.2.3"; the page says "EZdrummer 2"."""
    from src.scrapers.plugins.toontrack import ToontrackScraper

    name, versions = ToontrackScraper()._parse_page(EZDRUMMER_2)
    ezbass = ToontrackScraper()._parse_page(EZBASS)[1]

    assert name == "EZdrummer 2"
    assert ezbass[0].changelog.splitlines() == ["EZbass 1.3.4 is now available.", "BUG FIXES"]


def test_toontrack_drops_a_day_stamped_on_three_releases():
    """2018-03-16 on 2.1.1, 2.1.0 and 2.0.1 is the day the notes were imported."""
    from src.scrapers.plugins.toontrack import ToontrackScraper

    versions = ToontrackScraper()._parse_page(EZDRUMMER_2)[1]

    assert _dates(versions) == [("2.2.3", "2022-02-28"), ("2.1.2", "2016-06-10"), ("2.1.1", None),
                                ("2.1.0", None), ("2.0.2", "2015-04-23"), ("2.0.1", None)]


def test_toontrack_drops_only_the_date_that_contradicts_the_version_order():
    """2.4.3 dated before 2.4.0 and 2.4.2 loses its date; the two it contradicts keep theirs."""
    from src.scrapers.plugins.toontrack import ToontrackScraper

    versions = ToontrackScraper()._parse_page(SUPERIOR_DRUMMER_2)[1]

    assert _dates(versions) == [("2.4.4", "2016-06-10"), ("2.4.3", None), ("2.4.2", "2015-11-05"),
                                ("2.4.0", "2015-10-22"), ("2.3.1", "2012-11-26")]


def test_toontrack_reads_the_newest_build_per_product_from_the_versions_endpoint():
    from src.scrapers.plugins.toontrack import ToontrackScraper

    current = ToontrackScraper()._parse_api(_api(
        ("Superior Drummer 2.0", "2.4.4", "mac"), ("EZbass", "1.3.4", "mac"), ("EZbass", "1.3.5", "pc")))

    assert current == {"superior drummer 2": "2.4.4", "ezbass": "1.3.5"}


@pytest.mark.asyncio
async def test_toontrack_adds_a_current_version_the_endpoint_reports_ahead_of_the_notes():
    from src.scrapers.plugins.toontrack import ToontrackScraper as T

    scraper = T()
    listing = ('<html><body><a href="/release-notes/">All</a><a href="https://www.toontrack.com/release-notes/release-notes-ezbass/">EZbass</a>'
               '<a href="/release-notes/superior-drummer-2/">SD2</a><a href="/release-notes/release-notes-ezbass/#top">again</a></body></html>')
    asked = _stub_fetch(scraper, {
        T.LISTING_URL: listing,
        T.VERSIONS_API: _api(("EZbass", "1.3.5", "mac"), ("Superior Drummer 2.0", "2.4.4", "pc")),
        T.BASE_URL + "/release-notes/release-notes-ezbass/": EZBASS,
        T.BASE_URL + "/release-notes/superior-drummer-2/": SUPERIOR_DRUMMER_2,
    })

    devices = {d.name: d for d in (await scraper.fetch_device_list()).devices}
    ezbass = await scraper.fetch_firmware_versions("EZbass", devices["EZbass"].firmware_page_url)
    sd2 = await scraper.fetch_firmware_versions("Superior Drummer 2", devices["Superior Drummer 2"].firmware_page_url)

    assert sorted(devices) == ["EZbass", "Superior Drummer 2"]
    assert _dates(ezbass.firmware_versions)[:2] == [("1.3.5", None), ("1.3.4", "2026-05-29")]
    assert sd2.firmware_versions[0].version == "2.4.4"
    assert len(asked) == 4


@pytest.mark.asyncio
async def test_toontrack_fails_loudly_without_the_release_notes_listing():
    from src.scrapers.plugins.toontrack import ToontrackScraper as T

    scraper = T()
    _stub_fetch(scraper, {})

    assert (await scraper.fetch_device_list()).success is False
