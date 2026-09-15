import json
from datetime import datetime

import pytest

from tests.support import _stub_fetch


def _link(href, label):
    return (
        '<li class="elementor-icon-list-item"><a href="' + href + '">'
        '<span class="elementor-icon-list-icon"><i aria-hidden="true" class="fas fa-download"></i> </span>'
        '<span class="elementor-icon-list-text">' + label + "</span></a></li>"
    )


def _section(title, *items):
    return (
        '<div class="elementor-widget-container"><h2 class="elementor-heading-title elementor-size-default">'
        f"{title}</h2></div>"
        '<div class="elementor-widget-container"><ul class="elementor-icon-list-items">'
        + "".join(items) + "</ul></div>"
    )


UP = "https://oberheim.com/wp-content/uploads"
SUPPORT = (
    "<html><body>"
    + _section("Product Support", _link("https://oberheim.com/products/ob-x8/", "OB-X8"))
    + _section(
        "TEO-5 Support ",
        '<p>Press the Global button. The newest version of the TEO-5 Main OS is TEO-5_Main_v1.1.0.4.</p>',
        _link(f"{UP}/2025/11/TEO-5_Beta_Main_v1.2.0.15.zip", "TEO-5 Poly Chain OS BETA — v1.2.0.15"),
        _link(f"{UP}/2025/07/TEO-5_OS_Main_1.1.0.4.zip", "Latest TEO-5 OS — v1.1.0.4"),
        _link(f"{UP}/2024/07/TEO-5-Factory-Programs-ReadMe.zip", "TEO-5 Factory Programs — v1.0"),
    )
    + _section(
        "OB-X8 Support ",
        _link(f"{UP}/2024/07/OB-X8-OS2.0-Addendum.pdf", "Manual Addendum v2.0"),
        _link(f"{UP}/2024/08/OB-X8-OS-v2.0.0.1.zip", "Latest OB-X8 OS — v2.0.0.1"),
        _link(f"{UP}/2024/08/OB-X8-2.0.0.1-Changelog.txt", "OB-X8 OS — v2.0.0.1 Changelog"),
    )
    + _section(
        "OB-6 Support",
        _link("/files/downloads/OB-6/OB-6-Manual-Addendum-OS-v1.6.6.pdf", "Manual Addendum"),
        '<p>The current version is Main 1.8.0.</p>',
        _link("/files/downloads/OB-6/OB-6_OS-1.7.4.zip", "Previous OB-6 OS — v1.7.4"),
        _link(f"{UP}/2024/02/OB-6_OS-1.8.1.zip", "Latest OB-6 OS — v1.8.0"),
        _link("/files/downloads/OB-6/OB-6-Alternative-Tunings-ReadMe.zip", "OB-6 Alternative Tunings — v1.0"),
    )
    + '<h2 class="elementor-heading-title">Tour Playlist</h2>'
    + _link(f"{UP}/2020/01/Latest-Tour-OS-9.9.zip", "Latest Tour OS — v9.9")
    + "</body></html>"
)

CHANGELOG = """OBX8 Main 2.0.0.1 Changelog

Fixes:
- Calibration improvement

---------------------------



OBX8 Main 2.0.0.0 Changelog

New Features:
- Instant binaural mode pans individual voices hard left and right for true stereo operation

---------------------------



OBX8 Main 1.1.1.0 Changelog

Fixes:
- Local Control Off now works correctly
"""

POSTS = json.dumps([
    {"date": "2025-11-06T11:45:50", "title": {"rendered": "TEO-5 Poly Chain OS Update Now Available"}},
    {"date": "2025-10-01T09:00:00", "title": {"rendered": "TEO-5 OS v1.2.0.15 Beta Opens"}},
    {"date": "2024-07-02T09:58:20", "title": {"rendered": "Free OB-X8 OS v2.0 Update Delivers Powerful New Features "}},
    {"date": "2023-02-23T10:00:00", "title": {"rendered": "GForce Releases Oberheim OB-E v2.5 / SEM v1.5 Free Update"}},
])


def test_oberheim_reads_only_each_sections_latest_os_link():
    from src.scrapers.plugins.oberheim import OberheimScraper

    sections = OberheimScraper()._parse_support(SUPPORT)

    assert sections == {
        "TEO-5": ("1.1.0.4", None),
        "OB-X8": ("2.0.0.1", UP + "/2024/08/OB-X8-2.0.0.1-Changelog.txt"),
        "OB-6": ("1.8.1", None),
    }


def test_oberheim_trusts_the_file_name_over_the_link_label():
    from src.scrapers.plugins.oberheim import OberheimScraper

    label_only = SUPPORT.replace("OB-6_OS-1.8.1.zip", "OB-6_OS.zip")

    assert OberheimScraper()._parse_support(SUPPORT)["OB-6"][0] == "1.8.1"
    assert OberheimScraper()._parse_support(label_only)["OB-6"][0] == "1.8.0"


def test_oberheim_reads_history_and_notes_from_the_changelog_file():
    from src.scrapers.plugins.oberheim import OberheimScraper

    releases = OberheimScraper()._parse_changelog(CHANGELOG)

    assert [r.version for r in releases] == ["2.0.0.1", "2.0.0.0", "1.1.1.0"]
    assert releases[0].changelog == "Fixes:\n- Calibration improvement"
    assert releases[2].changelog == "Fixes:\n- Local Control Off now works correctly"


def test_oberheim_dates_a_release_only_from_a_post_naming_its_version():
    from src.scrapers.plugins.oberheim import OberheimScraper as S

    dates = S()._parse_posts(POSTS)

    assert dates == {("OB-X8", (2,)): datetime(2024, 7, 2)}
    assert S._version_key("2.0.0.0") == S._version_key("2.0") != S._version_key("2.0.0.1")


@pytest.mark.asyncio
async def test_oberheim_joins_the_page_changelog_and_posts():
    from src.scrapers.plugins.oberheim import OberheimScraper as S

    scraper = S()
    asked = _stub_fetch(scraper, {
        S.SUPPORT_URL: SUPPORT,
        S.POSTS_URL: POSTS,
        UP + "/2024/08/OB-X8-2.0.0.1-Changelog.txt": CHANGELOG,
    })

    devices = {d.name: d.category for d in (await scraper.fetch_device_list()).devices}
    obx8 = (await scraper.fetch_firmware_versions("OB-X8", S.SUPPORT_URL)).firmware_versions
    teo5 = (await scraper.fetch_firmware_versions("TEO-5", S.SUPPORT_URL)).firmware_versions

    assert devices == {"TEO-5": "synthesizer", "OB-X8": "synthesizer", "OB-6": "synthesizer"}
    assert [(r.version, r.release_date) for r in obx8] == [
        ("2.0.0.1", None), ("2.0.0.0", datetime(2024, 7, 2)), ("1.1.1.0", None),
    ]
    assert [(r.version, r.release_date, r.changelog) for r in teo5] == [("1.1.0.4", None, None)]
    assert len(asked) == 3


@pytest.mark.asyncio
async def test_oberheim_leads_with_a_current_os_the_changelog_has_not_caught_up_with():
    from src.scrapers.plugins.oberheim import OberheimScraper as S

    scraper = S()
    _stub_fetch(scraper, {
        S.SUPPORT_URL: SUPPORT.replace("OB-X8-OS-v2.0.0.1.zip", "OB-X8-OS-v2.0.0.2.zip"),
        UP + "/2024/08/OB-X8-2.0.0.1-Changelog.txt": CHANGELOG,
    })

    obx8 = (await scraper.fetch_firmware_versions("OB-X8", S.SUPPORT_URL)).firmware_versions

    assert [r.version for r in obx8] == ["2.0.0.2", "2.0.0.1", "2.0.0.0", "1.1.1.0"]


@pytest.mark.asyncio
async def test_oberheim_keeps_undated_releases_when_posts_fail():
    from src.scrapers.plugins.oberheim import OberheimScraper as S

    scraper = S()
    _stub_fetch(scraper, {S.SUPPORT_URL: SUPPORT})

    obx8 = await scraper.fetch_firmware_versions("OB-X8", S.SUPPORT_URL)

    assert obx8.success is True
    assert [(r.version, r.release_date) for r in obx8.firmware_versions] == [("2.0.0.1", None)]


@pytest.mark.asyncio
async def test_oberheim_fails_loudly_without_the_support_page():
    from src.scrapers.plugins.oberheim import OberheimScraper as S

    scraper = S()
    _stub_fetch(scraper, {})

    assert (await scraper.fetch_device_list()).success is False
