import json
from datetime import datetime

import pytest

from tests.support import _stub_fetch


def _release(tag, name, published, body="", prerelease=False, draft=False):
    return {"tag_name": tag, "name": name, "published_at": published, "created_at": published,
            "prerelease": prerelease, "draft": draft, "body": body,
            "assets": [{"name": f"deluge-community-{tag}.zip"}]}


RELEASES = [
    _release("beta", "Release 1.3.0 (beta 20260914)", "2026-09-14T09:00:00Z", "Rolling beta", prerelease=True),
    _release("release_1_2_1", "Release 1.2.1 (Chopin)", "2025-05-12T10:00:00Z",
             "This is a bugfix release based on 1.2.0\n\n## Changes from 1.2\n\n- Fixed audio clicks.\n"),
    _release("v1.2.0", "Release 1.2.0 (Chopin)", "2024-12-26T10:00:00Z", "## New features"),
    _release("release_1_10_draft", "Release 1.10.0 (draft)", "2026-01-01T10:00:00Z", draft=True),
    _release("release_1_0_1", "Release 1.0.1 (Amadeus)", "2024-01-08T10:00:00Z", "Fixes"),
    _release("release_1_0", "Community firmware", "2024-01-09T10:00:00Z", "First community release"),
]


def test_synthstrom_reads_only_stable_releases():
    from src.scrapers.plugins.synthstrom import SynthstromScraper

    releases = SynthstromScraper()._parse_releases(RELEASES)

    assert [r.version for r in releases] == ["1.2.1", "1.2.0", "1.0.1", "1.0"]
    assert releases[0].changelog.splitlines()[0] == "This is a bugfix release based on 1.2.0"


def test_synthstrom_takes_the_version_from_the_name_then_the_tag():
    from src.scrapers.plugins.synthstrom import SynthstromScraper

    scraper = SynthstromScraper()

    assert scraper._version({"name": "Release 1.2.1 (Chopin)", "tag_name": "release_9_9_9"}) == "1.2.1"
    assert scraper._version({"name": "Community firmware", "tag_name": "release_1_0"}) == "1.0"
    assert scraper._version({"name": "", "tag_name": "v1.2.0"}) == "1.2.0"
    assert scraper._version({"name": "Nightly", "tag_name": "nightly"}) is None


def test_synthstrom_drops_a_republished_date_that_follows_its_successor():
    from src.scrapers.plugins.synthstrom import SynthstromScraper

    releases = SynthstromScraper()._parse_releases(RELEASES)

    assert [(r.version, r.release_date) for r in releases] == [
        ("1.2.1", datetime(2025, 5, 12)), ("1.2.0", datetime(2024, 12, 26)),
        ("1.0.1", datetime(2024, 1, 8)), ("1.0", None),
    ]


def test_synthstrom_orders_releases_by_version_not_by_listing():
    from src.scrapers.plugins.synthstrom import SynthstromScraper

    shuffled = [RELEASES[4], RELEASES[1], RELEASES[5], RELEASES[2]]

    assert [r.version for r in SynthstromScraper()._parse_releases(shuffled)] == ["1.2.1", "1.2.0", "1.0.1", "1.0"]


@pytest.mark.asyncio
async def test_synthstrom_lists_the_deluge_from_one_short_page():
    from src.scrapers.plugins.synthstrom import SynthstromScraper as S

    scraper = S()
    asked = _stub_fetch(scraper, {S.releases_url(1): json.dumps(RELEASES)})

    devices = (await scraper.fetch_device_list()).devices
    deluge = await scraper.fetch_firmware_versions("Deluge", S.RELEASES_PAGE)

    assert [(d.name, d.category, d.firmware_page_url) for d in devices] == [("Deluge", "synthesizer", S.RELEASES_PAGE)]
    assert deluge.firmware_versions[0].version == "1.2.1"
    assert len(asked) == 1


@pytest.mark.asyncio
async def test_synthstrom_fails_loudly_when_a_page_does_not_load():
    from src.scrapers.plugins.synthstrom import SynthstromScraper as S

    scraper = S()
    full_page = [_release(f"release_1_{i}", f"Release 1.{i}.0", "2024-01-01T00:00:00Z") for i in range(S.PER_PAGE)]
    _stub_fetch(scraper, {S.releases_url(1): json.dumps(full_page)})

    assert (await scraper.fetch_device_list()).success is False
