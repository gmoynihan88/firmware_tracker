import json
from datetime import datetime

import pytest

from tests.support import _stub_fetch


def _github(tag, name, published, files=(), body="", prerelease=False, draft=False):
    return {"tag_name": tag, "name": name, "published_at": published, "prerelease": prerelease, "draft": draft,
            "body": body, "assets": [{"name": f} for f in files]}


def _gitlab(tag, name, released, links=(), description=""):
    return {"tag_name": tag, "name": name, "released_at": released, "upcoming_release": False,
            "description": description, "assets": {"count": len(links), "links": [{"name": l} for l in links]}}


MKII = [
    _github("2.2.2", "2.2.2", "2026-07-21T10:00:00Z", ["OXI_ONE_MKII_2_2_2.syx"], "Fixes for arpeggiator"),
    _github("2.0", "2.0.0", "2026-05-07T10:00:00Z", ["OXI_ONE_MKII_2_0_0.BETA.syx"], "Beta of 2.0"),
    _github("0.16.6", "0.16.7", "2025-08-14T10:00:00Z", ["OXI_ONE_MKII_0_16_7.syx"], "Bugfixes"),
    _github("0.14.5", "0.14.5", "2025-05-19T10:00:00Z", ["OXI_ONE_MKII_0_14_5.BETA.syx"]),
    _github("0.13.9", "0.13.9", "2025-04-30T10:00:00Z", ["OXI_ONE_MKII_0_13_9.syx"], prerelease=True),
]
ONE = [
    _gitlab("6.0", "6.0.2", "2026-05-05T10:00:00Z", ["6.0.2"], "## 6.0.2"),
    _gitlab("5.0.9", "5.0.9", "2025-07-18T10:00:00Z", ["5.0.9"]),
    _gitlab("4.2.4", "4.2.4", "2024-02-23T10:00:00Z", ["4.2.4"], "newer 4.2.4"),
    _gitlab("4.2.0", "4.2.4", "2024-02-21T10:00:00Z", ["4.2.4"], "older 4.2.4"),
    _gitlab("4.1.4", "4.1.4", "2024-03-01T10:00:00Z", ["4.1.4"]),
    _gitlab("4.0.11", "4.1.0", "2024-01-18T10:00:00Z", ["4.1.0"]),
    _gitlab("3.5.9", "3.5.9 BETA", "2023-04-05T10:00:00Z", ["3.5.9 BETA"]),
    _gitlab("v2.9b20", "v2.9b20", "2022-11-15T10:00:00Z"),
    _gitlab("v1.0.3", "v1.0.3 new release with several bugfixes", "2022-01-17T10:00:00Z"),
    _gitlab("v1.0.2c", "v1.0.2-pre fixed memory issues.", "2022-01-16T10:00:00Z"),
    _gitlab("v0.0.4", "EUCLIDEAN, 32 MIDI Ch, ANALOG Clock", "2021-07-07T10:00:00Z"),
]
CORAL = [
    _github("2.5", "2.5", "2025-02-24T10:00:00Z", ["CORAL_ACID_3VCO_2_5.bin", "CORAL_DRUMS_2_2_5.bin"]),
    _github("0.4.7", "", "2023-04-20T10:00:00Z", ["CORAL_0_4_7.bin"]),
]
E16 = [_github("v0.3.2", "0.3.2", "2025-04-07T10:00:00Z", ["OXI_E16_0_3_2.syx"])]
META = [_github("1.1", "1.1", "2024-08-21T10:00:00Z", ["META_1_1.bin"])]


def test_oxi_takes_the_release_name_over_a_lagging_tag():
    from src.scrapers.plugins.oxi import OXIScraper

    scraper = OXIScraper()

    assert [r.version for r in scraper._parse_feed(ONE)] == ["6.0.2", "5.0.9", "4.2.4", "4.1.4", "4.1.0", "1.0.3"]
    assert [r.version for r in scraper._parse_feed(CORAL)] == ["2.5", "0.4.7"]
    assert [r.version for r in scraper._parse_feed(E16)] == ["0.3.2"]


def test_oxi_skips_releases_whose_firmware_file_is_marked_beta():
    from src.scrapers.plugins.oxi import OXIScraper

    releases = OXIScraper()._parse_feed(MKII)

    assert [(r.version, r.release_date, r.changelog) for r in releases] == [
        ("2.2.2", datetime(2026, 7, 21), "Fixes for arpeggiator"), ("0.16.7", datetime(2025, 8, 14), "Bugfixes"),
    ]


def test_oxi_keeps_the_newer_of_a_name_published_twice_and_drops_an_out_of_order_date():
    from src.scrapers.plugins.oxi import OXIScraper

    releases = {r.version: r for r in OXIScraper()._parse_feed(ONE)}

    assert (releases["4.2.4"].release_date, releases["4.2.4"].changelog) == (datetime(2024, 2, 23), "newer 4.2.4")
    assert releases["4.1.4"].release_date is None
    assert releases["4.1.0"].release_date == datetime(2024, 1, 18)


@pytest.mark.asyncio
async def test_oxi_reads_every_feed_following_pages_until_a_short_one():
    from src.scrapers.plugins.oxi import OXIScraper as S

    scraper = S()
    full_page = [_gitlab(f"3.{i}", f"3.{i}", "2023-01-01T00:00:00Z", [f"3.{i}"]) for i in range(S.PER_PAGE)]
    asked = _stub_fetch(scraper, {
        S.feed_url("github", "OXI-Instruments/OXI-One-MkII-Releases", 1): json.dumps(MKII),
        S.feed_url("gitlab", "25470905", 1): json.dumps(ONE[:3] + full_page[:S.PER_PAGE - 3]),
        S.feed_url("gitlab", "25470905", 2): json.dumps(ONE[3:]),
        S.feed_url("github", "OXI-Instruments/OXI-E16-Releases", 1): json.dumps(E16),
        S.feed_url("github", "oxiinstruments/coral-releases", 1): json.dumps(CORAL),
        S.feed_url("github", "oxiinstruments/meta-releases", 1): json.dumps(META),
    })

    devices = {d.name: d.category for d in (await scraper.fetch_device_list()).devices}
    one = await scraper.fetch_firmware_versions("OXI One", S.SUPPORT_URL)

    assert devices == {"OXI One MKII": "midi_controller", "OXI One": "midi_controller", "OXI E16": "midi_controller",
                       "OXI Coral": "synthesizer", "OXI Meta": "other"}
    assert [r.version for r in one.firmware_versions][:5] == ["6.0.2", "5.0.9", "4.2.4", "4.1.4", "4.1.0"]
    assert len(one.firmware_versions) == S.PER_PAGE - 3 + 6
    assert len(asked) == 6


@pytest.mark.asyncio
async def test_oxi_reports_a_failed_feed_empty_and_fails_only_when_all_do():
    from src.scrapers.plugins.oxi import OXIScraper as S

    partial = S()
    _stub_fetch(partial, {S.feed_url("github", "oxiinstruments/meta-releases", 1): json.dumps(META)})
    assert (await partial.fetch_device_list()).success is True
    assert (await partial.fetch_firmware_versions("OXI Coral", S.SUPPORT_URL)).firmware_versions == []

    none = S()
    _stub_fetch(none, {})
    assert (await none.fetch_device_list()).success is False
