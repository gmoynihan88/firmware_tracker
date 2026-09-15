import json

import pytest

from tests.support import _stub_fetch


def _pg_release(date, heading, *notes):
    """One release as the Help Center writes it: date above, bold heading, notes below."""
    return (
        (f"<p><strong>{date}</strong></p>" if date else "")
        + f'<p><strong><span class="wysiwyg-color-orange70">{heading}</span></strong></p>'
        + ("<ul>" + "".join(f"<li>{note}</li>" for note in notes) + "</ul>" if notes else "")
    )


def test_positivegrid_reads_every_heading_form():
    """Including the one "Changed in" the BIAS Amp article slipped in among its "Changes in"."""
    from src.scrapers.plugins.positivegrid import PositiveGridScraper

    scraper = PositiveGridScraper()
    for heading, version in (
        ("Changes in BIAS FX 2 Desktop 2.7.0.6600", "2.7.0.6600"),
        ("Changed in BIAS Amp Desktop 1.4.3.2338", "1.4.3.2338"),
        ("Changes in BIAS Amp Desktop 1.0.7 (Initial release)", "1.0.7"),
        ("Spark 2 firmware ver. 2.7.2.200 / rev490", "2.7.2.200"),
        ("Spark LIVE firmware ver. 2.9.4.209 / rev 498", "2.9.4.209"),
        ("Spark MINI firmware v1.10.2.57 (Bluetooth Firmware v1.90)", "1.10.2.57"),
        ("Spark firmware 1.10.8.25", "1.10.8.25"),
        ("BIAS X ver. 1.2.4", "1.2.4"),
    ):
        versions = scraper._parse_article(_pg_release(None, heading, "A fix"))
        assert [fw.version for fw in versions] == [version], heading


def test_positivegrid_ignores_the_versions_the_notes_mention():
    from src.scrapers.plugins.positivegrid import PositiveGridScraper

    body = (
        _pg_release("Mar 31, 2025", "Changes in BIAS Amp Desktop 1.6.0.4529",
                    'Fixed "BIAS FX v1.6.8 crashes Pro Tools"')
        + "<p>Updated bundled BIAS GEAR firmware to 0.5.2.193</p>"
        + "<p>Increased USB recording volume (for units shipped with firmware version 0.1.2.197).</p>"
        + "<p>Input gain ratio: 0.23.</p>"
        # A paragraph that contains a heading's shape without being one.
        + "<p>Make sure your Spark firmware 1.9.7.246 is installed first.</p>"
    )

    versions = PositiveGridScraper()._parse_article(body)

    assert [fw.version for fw in versions] == ["1.6.0.4529"]
    assert "Updated bundled BIAS GEAR firmware to 0.5.2.193" in versions[0].changelog


def test_positivegrid_pairs_each_version_with_the_date_directly_above_it():
    """Six date formats, a bare bold date, and a factory release under no date at all."""
    from src.scrapers.plugins.positivegrid import PositiveGridScraper

    body = (
        _pg_release("3/16/2021", "Changes in BIAS FX 2 Desktop 2.7.0.6600", "Fix")
        + _pg_release("08/31/2023", "Changes in BIAS FX 2 Desktop 2.6.1.6290", "Fix")
        + _pg_release("11.8.2019", "Changes in BIAS FX 2 Desktop 2.1.6.4812", "Fix")
        + _pg_release("July 15. 2024", "Spark firmware 1.10.8.25", "Fix")
        + _pg_release("Mar 31, 2025", "Spark 2 firmware ver. 2.7.2.200 / rev490", "Fix")
        + "<strong>August 30, 2024</strong>"
        + '<p><strong>Spark Control X firmware ver. 4.1.23</strong></p><ul><li>Fix</li></ul>'
        + "<p><strong>Factory Version</strong></p>"
        + '<p><strong>Spark PEDAL firmware ver. 2.8.1.101</strong></p>'
        # A date with something else between it and the next heading is not that heading's.
        + "<p><strong>June 2, 2026</strong></p><p>Known issue: none.</p>"
        + '<p><strong>Spark PEDAL firmware ver. 2.7.0.90</strong></p>'
    )

    dated = {fw.version: fw.release_date.date().isoformat() if fw.release_date else None
             for fw in PositiveGridScraper()._parse_article(body)}

    assert dated == {
        "2.7.0.6600": "2021-03-16",
        "2.6.1.6290": "2023-08-31",
        "2.1.6.4812": "2019-11-08",
        "1.10.8.25": "2024-07-15",
        "2.7.2.200": "2025-03-31",
        "4.1.23": "2024-08-30",
        "2.8.1.101": None,
        "2.7.0.90": None,
    }


def test_positivegrid_dates_a_repeated_version_by_its_first_release():
    """Spark MINI lists 1.11.2.75 again beside a later Bluetooth-only update."""
    from src.scrapers.plugins.positivegrid import PositiveGridScraper

    versions = PositiveGridScraper()._parse_article(
        _pg_release("Mar 5, 2026", "Spark MINI firmware v1.11.2.75 (Bluetooth Firmware v1.91)", "Bluetooth fix")
        + _pg_release("May 13, 2024", "Spark MINI firmware v1.11.2.75", "Firmware fix")
    )

    assert [(fw.version, fw.release_date.date().isoformat()) for fw in versions] == [("1.11.2.75", "2024-05-13")]
    assert versions[0].changelog.splitlines() == ["- Bluetooth fix", "- Firmware fix"]


def _pg_article(title, body, article_id=1):
    return {"id": article_id, "title": title, "locale": "en-us", "body": body,
            "html_url": f"https://help.positivegrid.com/hc/en-us/articles/{article_id}"}


def _pg_search(extra_hardware=8):
    """Two search pages: products, apps, a product with no release yet, and filler hardware."""
    from src.scrapers.plugins.positivegrid import PositiveGridScraper as PG

    release = _pg_release("Jan 16, 2025", "Spark GO firmware ver. 1.15.0.209", "Fix")
    first = [
        _pg_article("Spark (40) Firmware Release Notes", _pg_release("July 15. 2024", "Spark firmware 1.10.8.25", "Fix"), 1),
        _pg_article("Spark Control X Firmware Release Notes", _pg_release(None, "Spark Control X firmware ver. 4.1.23", "Fix"), 2),
        _pg_article("BIAS FX 2 Desktop Update History / Release Notes", _pg_release("11/1/2023", "Changes in BIAS FX 2 Desktop 2.7.0.6600", "Fix"), 3),
        _pg_article("BIAS X Update History / Release Notes", _pg_release("August 19, 2026", "BIAS X ver. 1.2.4", "Fix"), 4),
        _pg_article("BIAS FX 2 Mobile Update History & Release Notes", _pg_release(None, "Changes in BIAS FX 2 Mobile 3.0.0", "Fix"), 5),
        _pg_article("Spark App Update History / Release Notes (iOS / iPadOS)", _pg_release(None, "Spark App ver. 4.0.0", "Fix"), 6),
        _pg_article("JamUp Update History / Release Notes", _pg_release(None, "JamUp ver. 5.0.0", "Fix"), 7),
        _pg_article("REACTOR 50/100 Firmware Release Notes", "<div>No new firmware has been released yet.</div>", 8),
    ]
    second = [_pg_article(f"Spark Unit {n} Firmware Release Notes", release, 100 + n) for n in range(extra_hardware)]
    next_url = PG.SEARCH_URL + "&page=2"
    return {
        PG.SEARCH_URL: json.dumps({"results": first, "next_page": next_url}),
        next_url: json.dumps({"results": second, "next_page": None}),
    }


@pytest.mark.asyncio
async def test_positivegrid_catalogues_hardware_and_plugins_but_not_apps():
    from src.scrapers.plugins.positivegrid import PositiveGridScraper as PG

    scraper = PG()
    asked = _stub_fetch(scraper, _pg_search())

    devices = {d.name: d.category for d in (await scraper.fetch_device_list()).devices}
    history = await scraper.fetch_firmware_versions("Spark 40", "")

    assert len(asked) == 2  # both search pages, once
    assert {name: devices[name] for name in ("Spark 40", "Spark Control X", "BIAS FX 2", "BIAS X")} == {
        "Spark 40": "guitar_pedal",
        "Spark Control X": "midi_controller",
        "BIAS FX 2": "vst_plugin",
        "BIAS X": "vst_plugin",
    }
    assert not any("Mobile" in name or "App" in name or "JamUp" in name for name in devices)
    assert "REACTOR 50/100" not in devices  # no release yet
    assert [fw.version for fw in history.firmware_versions] == ["1.10.8.25"]


@pytest.mark.asyncio
async def test_positivegrid_fails_loudly_when_the_search_comes_back_thin():
    """A broken search looks like a vendor that withdrew its products."""
    from src.scrapers.plugins.positivegrid import PositiveGridScraper as PG

    scraper = PG()
    _stub_fetch(scraper, _pg_search(extra_hardware=0))

    assert (await scraper.fetch_device_list()).success is False
