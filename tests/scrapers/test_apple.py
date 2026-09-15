import json
from datetime import datetime

import pytest

from tests.support import _stub_fetch


APPLE_LOGIC_12 = """<html><body><div id="app"><div id="content"><div id="sections">
<h1 class="gb-header">Logic Pro for Mac release notes</h1>
<h2 class="gb-header">New in Logic Pro 12.3.1</h2> <p class="gb-paragraph">Beat Mapping</p>
<ul class="list gb-list"><li><p class="gb-paragraph">Restores the ability to relocate beat mapping transients.</p></li></ul>
<h3 class="gb-header">Logic Pro for Mac 12.3</h3> <p class="gb-paragraph">New features and enhancements</p>
<ul class="list gb-list"><li><p class="gb-paragraph">Beat Breaker slices loops.</p></li><li><p class="gb-paragraph">Retro Synth no longer clicks.</p></li></ul>
<h3 class="gb-header">Logic Pro for iPad 2.3</h3> <p class="gb-paragraph">Notes for the iPad app.</p>
<h2 class="gb-header">Learn more</h2> <ul class="list gb-list"><li><p class="gb-paragraph">For previous Logic Pro release notes, see Logic Pro 11 release notes.</p></li></ul>
<div>Information about products not manufactured by Apple is provided without recommendation.</div>
<div class="mod-date">Published Date: August 14, 2026</div>
</div></div></div></body></html>"""


APPLE_LOGIC_11 = """<html><body><div id="sections">
<h1 class="gb-header">Logic Pro for Mac 11 release notes</h1>
<h3 class="gb-header">Logic 11.2</h3> <p class="gb-paragraph">Flashback Capture recovers a performance.</p>
<h3 class="gb-header">Logic Pro 11.0</h3> <p class="gb-paragraph">Session Players join Drummer.</p>
<div class="mod-date">Published Date: April 09, 2026</div>
</div></body></html>"""


APPLE_LOGIC_10_0 = """<html><body><div id="sections">
<h1 class="gb-header">Logic Pro 10.0 Release Notes</h1>
<h2 class="gb-header">Logic Pro X 10.0.6 update</h2> <p class="gb-paragraph"><b>Stability</b></p>
<ul class="list gb-list"><li><p class="gb-paragraph">Fixes an audio-input issue.</p></li></ul>
<div class="mod-date">Published Date: October 26, 2023</div>
</div></body></html>"""


def _apple_lookup(version, released="2026-08-13T16:59:07Z", notes="This update includes stability improvements and bug fixes"):
    return json.dumps({"resultCount": 1, "results": [
        {"version": version, "currentVersionReleaseDate": released, "releaseNotes": notes}]})


def _apple_scraper(logic="12.3.1", mainstage="4.3.1", missing=()):
    """An AppleScraper reading three articles, with the fetches stubbed."""
    from src.scrapers.plugins.apple import AppleScraper as A

    scraper = A()
    urls = ["https://support.apple.com/en-us/HT203718", "https://support.apple.com/en-us/126835",
            "https://support.apple.com/kb/HT204982"]
    scraper.RELEASE_NOTES_URLS = urls
    pages = dict(zip(urls, (APPLE_LOGIC_12, APPLE_LOGIC_11, APPLE_LOGIC_10_0)))
    pages[A.LOOKUP_URL.format(app_id=634148309)] = _apple_lookup(logic)
    pages[A.LOOKUP_URL.format(app_id=634159523)] = _apple_lookup(mainstage, "2026-08-13T17:01:59Z")
    for url in missing:
        pages.pop(url)
    asked = _stub_fetch(scraper, pages)
    return scraper, asked


def test_logic_reads_every_heading_wording_but_not_the_title_or_the_ipad_app():
    """ "Logic 11.2" and "Logic Pro X 10.0.6 update" are releases; the h1 and "Logic Pro for iPad 2.3" are not."""
    from src.scrapers.plugins.apple import AppleScraper

    scraper = AppleScraper()

    assert [fw.version for fw in scraper._parse_release_notes(APPLE_LOGIC_12)] == ["12.3.1", "12.3"]
    assert [fw.version for fw in scraper._parse_release_notes(APPLE_LOGIC_11)] == ["11.2", "11.0"]
    assert [fw.version for fw in scraper._parse_release_notes(APPLE_LOGIC_10_0)] == ["10.0.6"]


def test_logic_notes_stop_at_the_next_heading_and_before_the_article_footer():
    from src.scrapers.plugins.apple import AppleScraper

    scraper = AppleScraper()
    notes = {fw.version: fw.changelog for fw in scraper._parse_release_notes(APPLE_LOGIC_12)}
    oldest = scraper._parse_release_notes(APPLE_LOGIC_10_0)[0].changelog

    assert notes["12.3"].splitlines() == [
        "New features and enhancements", "- Beat Breaker slices loops.", "- Retro Synth no longer clicks.",
    ]
    assert oldest.splitlines() == ["Stability", "- Fixes an audio-input issue."]


@pytest.mark.asyncio
async def test_logic_dates_only_the_version_the_app_store_says_is_current():
    """The articles date nothing, and "Published Date" is the article's own."""
    scraper, _ = _apple_scraper()

    result = await scraper.fetch_firmware_versions("Logic Pro", "https://support.apple.com/en-us/HT203718")
    dated = {fw.version: fw.release_date for fw in result.firmware_versions}

    assert list(dated) == ["12.3.1", "12.3", "11.2", "11.0", "10.0.6"]
    assert dated["12.3.1"] == datetime(2026, 8, 13, 16, 59, 7)
    assert [v for v, released in dated.items() if released] == ["12.3.1"]
    assert result.firmware_versions[0].changelog.startswith("Beat Mapping")


@pytest.mark.asyncio
async def test_logic_takes_a_release_the_article_has_not_reached_from_the_app_store():
    scraper, _ = _apple_scraper(logic="12.4")

    result = await scraper.fetch_firmware_versions("Logic Pro", "https://support.apple.com/en-us/HT203718")
    latest = next(fw for fw in result.firmware_versions if fw.version == "12.4")

    assert latest.release_date == datetime(2026, 8, 13, 16, 59, 7)
    assert latest.changelog == "This update includes stability improvements and bug fixes"


@pytest.mark.asyncio
async def test_mainstage_is_the_app_stores_current_version_alone():
    scraper, _ = _apple_scraper()

    devices = {d.name: d.category for d in (await scraper.fetch_device_list()).devices}
    result = await scraper.fetch_firmware_versions("MainStage", "https://apps.apple.com/us/app/mainstage/id634159523")

    assert devices == {"Logic Pro": "vst_plugin", "MainStage": "vst_plugin"}
    assert [(fw.version, fw.release_date) for fw in result.firmware_versions] == [("4.3.1", datetime(2026, 8, 13, 17, 1, 59))]


@pytest.mark.asyncio
async def test_logic_fails_loudly_when_an_archived_article_is_missing():
    """A history with a hole in it is never stored as complete."""
    scraper, asked = _apple_scraper(missing=["https://support.apple.com/en-us/126835"])

    assert (await scraper.fetch_device_list()).success is False
    assert "https://support.apple.com/kb/HT204982" not in asked
