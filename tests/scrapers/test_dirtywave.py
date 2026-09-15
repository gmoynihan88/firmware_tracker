from datetime import datetime

import pytest

from tests.support import _stub_fetch

CHANGELOG = """2026-09-13 - Version 6.6.3 C
- Fix: MIDI intruments CC values always sent on instrument trigger. Now only sent on song start, instrument change, or the CC value changes

2026-09-10 - Version 6.6.3 A
- Fix: MIDI instrument did not show notes on the right info area

2026-09-07 - Version 6.6.3
- Improved: Recording - Mitigated audio dropouts while recording and playing back song at the same time
- Fix: PSL pitch slide was not reset on instrument retrigger

2025-07-01 - Version 6.0.2A
- Fix: Sampler slices could play the wrong region

2022-03-02 - Version 2.7.1
- Fix: Newer entry for 2.7.1

2022-02-27 - Version 2.7.1
- Fix: Older entry for 2.7.1

2021-05-29 - Version 2.0.0 - Official Production Unit Version Support
- New: Headphone amp control

2020-11-10 - Version 1.0.4
- Fix: crash on boot

2020-24-10 - Version 1.0.3
- Fix: sample browser

2020-23-09 - Version 1.0.0
- Initial release
"""


def test_dirtywave_reads_every_release_with_its_suffix_letter():
    from src.scrapers.plugins.dirtywave import DirtywaveScraper

    releases = DirtywaveScraper()._parse(CHANGELOG)

    assert [r.version for r in releases] == ["6.6.3C", "6.6.3A", "6.6.3", "6.0.2A", "2.7.1", "2.0.0", "1.0.4", "1.0.3", "1.0.0"]
    assert releases[2].changelog.splitlines() == [
        "- Improved: Recording - Mitigated audio dropouts while recording and playing back song at the same time",
        "- Fix: PSL pitch slide was not reset on instrument retrigger",
    ]


def test_dirtywave_reads_day_first_dates_where_the_month_cannot_be_the_month():
    from src.scrapers.plugins.dirtywave import DirtywaveScraper

    releases = {r.version: r.release_date for r in DirtywaveScraper()._parse(CHANGELOG)}

    assert releases["6.6.3C"] == datetime(2026, 9, 13)
    assert releases["1.0.4"] == datetime(2020, 11, 10)
    assert releases["1.0.3"] == datetime(2020, 10, 24)
    assert releases["1.0.0"] == datetime(2020, 9, 23)
    assert DirtywaveScraper._parse_date("2020-31-31") is None


def test_dirtywave_keeps_a_header_note_and_the_newer_of_a_repeated_entry():
    from src.scrapers.plugins.dirtywave import DirtywaveScraper

    releases = {r.version: r for r in DirtywaveScraper()._parse(CHANGELOG)}

    assert releases["2.0.0"].changelog == "Official Production Unit Version Support\n- New: Headphone amp control"
    assert (releases["2.7.1"].release_date, releases["2.7.1"].changelog) == (datetime(2022, 3, 2), "- Fix: Newer entry for 2.7.1")


@pytest.mark.asyncio
async def test_dirtywave_lists_the_m8_from_the_change_log():
    from src.scrapers.plugins.dirtywave import DirtywaveScraper as S

    scraper = S()
    asked = _stub_fetch(scraper, {S.CHANGELOG_URL: CHANGELOG})

    devices = (await scraper.fetch_device_list()).devices
    m8 = await scraper.fetch_firmware_versions("M8", S.PAGE_URL)

    assert [(d.name, d.category, d.firmware_page_url) for d in devices] == [("M8", "synthesizer", S.PAGE_URL)]
    assert m8.firmware_versions[0].version == "6.6.3C"
    assert len(asked) == 1


@pytest.mark.asyncio
async def test_dirtywave_fails_loudly_without_the_change_log():
    from src.scrapers.plugins.dirtywave import DirtywaveScraper as S

    scraper = S()
    _stub_fetch(scraper, {})

    assert (await scraper.fetch_device_list()).success is False
