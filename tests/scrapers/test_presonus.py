import json
from datetime import datetime

import pytest

from tests.support import _stub_fetch


STUDIO_BODY = (
    '<p><strong>1.3 (113142/113218) Jul 30, 2026</strong><br/>Release Guide: <a href="https://shorturl.at/kGfwG">https://shorturl.at/kGfwG</a></p>'
    '<figure class="wysiwyg-table"><table><tbody>'
    "<tr><td>Issue Type</td><td>Issue key</td><td>Summary</td></tr>"
    "<tr><td>Bug</td><td>FES-901</td><td>[Android] Purchase issue in Samsung Galaxy Store</td></tr>"
    "<tr><td>Task</td><td>FES-910</td><td>Marketing consent checkbox for sign-in</td></tr>"
    "</tbody></table></figure>"
    "<p><strong>1.2.2 (111164) Mar 24, 2026</strong><br/>Release Guide: https://shorturl.at/x</p>"
    "<figure><table><tbody><tr><td>Issue Type</td><td>Issue key</td><td>Summary</td></tr>"
    "<tr><td>Bug</td><td>FES-850</td><td>Crash on launch</td></tr></tbody></table></figure>"
)

NOTION_BODY = (
    '<p><strong>Fender Notion 3.7.1: Aug 2026</strong><br/>Guide: <a href="https://shorturl.at/sAETQ">https://shorturl.at/sAETQ</a></p>'
    "<p>NS-4641 [iOS] Restored purchases list as expected<br/>General stability fixes<br/> </p>"
    "<p><strong>Fender Notion 3.6.3: Apr 2026 (Android only)</strong></p><p>NS-4500 Android fix</p>"
    "<p><strong>Notion Mobile 3.5.1: Sept 2025</strong></p><p>Fixes</p>"
    "<p><br/><strong>Notion Mobile 3.0.4:</strong><br/>Improvements<br/>Stability fixes and performance improvements</p>"
    "<p><strong>Version 2.6.2 (Oct 19th 2021)</strong></p><p>Bug fixes</p>"
    "<p><strong>Version 2.0.157 (Oct 17 2016)</strong></p><p>Support for iOS 10</p>"
    "<p><strong>ersion 1.2.66 (Jul 31, 2013)</strong></p><p>Stability</p>"
)

NOTION6_PAGE = """<html><head><style>pre { font: 8pt verdana; }</style></head><body>
<pre>
<big> <b>6.8.2 Build 18133</b> <b>Aug 24, 2021</b> </big>
<b>New</b>
    'Insert multiple barlines' tool added.
<b>Fixes</b>
    [Win] Crash fixed when exporting MIDI
<big> <b>6.8.1 Build 18093</b> <b>Mar 9, 2021</b> </big>
<b>Improvements</b>
    Scrollbars enabled by default on Big Sur
</pre></body></html>"""


def _search(*articles):
    return json.dumps({"results": [{"id": i, "title": title, "body": body} for i, (title, body) in enumerate(articles)]})


def _pairs(releases):
    return [(fw.version, fw.release_date.date().isoformat() if fw.release_date else None) for fw in releases]


def test_presonus_fender_studio_reads_the_version_not_the_build_and_the_issue_table():
    from src.scrapers.plugins.presonus import PreSonusScraper as P

    releases = P()._parse_article(STUDIO_BODY, P.STUDIO_HEADING)

    assert _pairs(releases) == [("1.3", "2026-07-30"), ("1.2.2", "2026-03-24")]
    assert releases[0].changelog.splitlines() == [
        "Bug FES-901 [Android] Purchase issue in Samsung Galaxy Store", "Task FES-910 Marketing consent checkbox for sign-in",
    ]


def test_presonus_notion_reads_every_heading_shape_and_invents_no_date():
    """Month-only dates land on the 1st; "Notion Mobile 3.0.4:" has none; "ersion" lost its V."""
    from src.scrapers.plugins.presonus import PreSonusScraper as P

    releases = P()._parse_article(NOTION_BODY, P.NOTION_HEADING)

    assert _pairs(releases) == [
        ("3.7.1", "2026-08-01"), ("3.6.3", "2026-04-01"), ("3.5.1", "2025-09-01"), ("3.0.4", None),
        ("2.6.2", "2021-10-19"), ("2.0.157", "2016-10-17"), ("1.2.66", "2013-07-31"),
    ]


def test_presonus_notion_notes_include_lines_inside_the_heading_paragraph_and_stop_at_the_next():
    from src.scrapers.plugins.presonus import PreSonusScraper as P

    releases = {fw.version: fw for fw in P()._parse_article(NOTION_BODY, P.NOTION_HEADING)}

    assert releases["3.0.4"].changelog.splitlines() == ["Improvements", "Stability fixes and performance improvements"]
    assert releases["3.7.1"].changelog.splitlines() == ["NS-4641 [iOS] Restored purchases list as expected", "General stability fixes"]


def test_presonus_notion6_reads_the_preformatted_change_log():
    from src.scrapers.plugins.presonus import PreSonusScraper

    releases = PreSonusScraper()._parse_notion6(NOTION6_PAGE)

    assert _pairs(releases) == [("6.8.2", "2021-08-24"), ("6.8.1", "2021-03-09")]
    assert releases[0].changelog.splitlines() == [
        "New", "'Insert multiple barlines' tool added.", "Fixes", "[Win] Crash fixed when exporting MIDI",
    ]


@pytest.mark.asyncio
async def test_presonus_finds_each_article_by_its_exact_title():
    """ "Fender Notion is here..." comes back from the same search and is not the release notes."""
    from src.scrapers.plugins.presonus import PreSonusScraper as P

    scraper = P()
    asked = _stub_fetch(scraper, {
        P.search_url("Fender Studio Release Notes"): _search(("Fender Studio Release Notes", STUDIO_BODY)),
        P.search_url("Fender Notion Release Notes"): _search(
            ("Fender Notion is here...", "<p><strong>Version 9.9 (Jan 1, 2030)</strong></p>"),
            ("Fender Notion Release Notes", NOTION_BODY)),
        P.NOTION6_URL: NOTION6_PAGE,
    })

    devices = {d.name: d.category for d in (await scraper.fetch_device_list()).devices}
    notion = await scraper.fetch_firmware_versions("Fender Notion", "")

    assert devices == {"Fender Studio": "vst_plugin", "Fender Notion": "vst_plugin", "Notion 6": "vst_plugin"}
    assert notion.firmware_versions[0].version == "3.7.1"
    assert len(asked) == 3


@pytest.mark.asyncio
async def test_presonus_fails_loudly_when_no_source_can_be_read():
    from src.scrapers.plugins.presonus import PreSonusScraper as P

    scraper = P()
    _stub_fetch(scraper, {})

    assert (await scraper.fetch_device_list()).success is False
