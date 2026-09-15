from datetime import datetime

import pytest

from tests.support import _stub_fetch


def _entry(title, date, body):
    anchor = title.lower().replace(" ", "-").replace(".", "")
    return (
        f'<h2 class="anchor anchorTargetStickyNavbar_Vzrq" id="{anchor}">{title}<a href="#{anchor}" class="hash-link" '
        f'aria-label="Direct link to {title}" title="Direct link to {title}" translate="no">​</a></h2>\n'
        f"<p><strong>{date}</strong></p>\n{body}\n"
    )


def _section(name, items):
    return (
        f'<h3 class="anchor anchorTargetStickyNavbar_Vzrq" id="{name.lower()}">{name}<a href="#{name.lower()}" '
        f'class="hash-link" translate="no">​</a></h3>\n<ul>\n' + "".join(f'<li class="">{i}</li>\n' for i in items) + "</ul>"
    )


def _page(*entries, intro=""):
    return (
        '<html><head><meta name="generator" content="Docusaurus v3.9.2"></head><body>'
        '<nav><a href="/t1/introduction">T-1</a></nav>'
        '<div class="theme-doc-markdown markdown"><header><h1>| Changelog</h1></header>\n'
        + intro + "<hr>\n" + "".join(entries) + "</div></body></html>"
    )


T1 = _page(
    _entry("v2.1.5", "Aug 5, 2026",
           _section("Bugfixes", ["Fixed an issue where <strong>TEMP + SAVE</strong> was jumping to the beginning of sequence",
                                 'Updated <strong>CONFIG APP</strong>\n<ul>\n<li class="">Fixed a GUI issue</li>\n</ul>\n'])
           + '\n<p>Get the update at: <a href="https://torsoelectronics.com/pages/support">support</a></p>'),
    _entry("v2.1.0", "December 16 2025", _section("Features", ["Scales"])),
    _entry("v2.0.4", "January 30, 2023", _section("Bugfixes", ["Same-day hotfix"])),
    _entry("v2.0.3", "January 30, 2023", _section("Bugfixes", ["Clock fix"])),
    _entry("v2.0.2", "November 21, 2022", _section("Bugfixes", ["Swing fix"])),
    _entry("v2.0.1", "December 13, 2022", _section("Bugfixes", ["MIDI fix"])),
    _entry("v2.0.0", "December 9, 2022", _section("Features", ["Pattern chaining"])),
)
S4 = _page(
    _entry("Changes in S4 OS v2.2.0", "June 3, 2026", _section("Features", ["<strong>MOSAIC:</strong> Device update"])),
    _entry("S4 OS v2.1.3 Hotfix", "February 20, 2026", _section("Bugfixes", ["Crash fix"])),
    _entry("S4 OS v2.0", "June 17, 2025", _section("Features", ["New devices"])),
    intro='<div class="theme-admonition"><p>Get the latest update at: <a href="https://torsoelectronics.com/pages/support">'
          "https://torsoelectronics.com/pages/support</a></p></div>",
)
HOME = (
    '<html><body><a href="/t1/introduction">T-1</a><a href="/t1/changelog/">T-1 changelog</a>'
    '<a href="/s4/introduction">S-4</a><a href="/ja/t1/introduction">日本語</a><a href="/blog/">Blog</a></body></html>'
)
D = "https://docs.torsoelectronics.com"


def test_torso_reads_the_version_from_either_heading_shape():
    from src.scrapers.plugins.torso import TorsoScraper

    scraper = TorsoScraper()

    assert [r.version for r in scraper._parse_changelog(T1)][:2] == ["2.1.5", "2.1.0"]
    assert [(r.version, r.release_date) for r in scraper._parse_changelog(S4)] == [
        ("2.2.0", datetime(2026, 6, 3)), ("2.1.3", datetime(2026, 2, 20)), ("2.0", datetime(2025, 6, 17)),
    ]


def test_torso_drops_only_the_date_that_breaks_version_order():
    from src.scrapers.plugins.torso import TorsoScraper

    releases = TorsoScraper()._parse_changelog(T1)

    assert [(r.version, r.release_date) for r in releases] == [
        ("2.1.5", datetime(2026, 8, 5)), ("2.1.0", datetime(2025, 12, 16)), ("2.0.4", datetime(2023, 1, 30)),
        ("2.0.3", datetime(2023, 1, 30)),
        ("2.0.2", None), ("2.0.1", datetime(2022, 12, 13)), ("2.0.0", datetime(2022, 12, 9)),
    ]


def test_torso_notes_keep_headings_and_nested_items_but_not_the_update_link():
    from src.scrapers.plugins.torso import TorsoScraper

    releases = TorsoScraper()._parse_changelog(T1)

    assert releases[0].changelog.splitlines() == [
        "Bugfixes", "Fixed an issue where TEMP + SAVE was jumping to the beginning of sequence",
        "Updated CONFIG APP", "Fixed a GUI issue",
    ]


@pytest.mark.asyncio
async def test_torso_discovers_products_from_the_docs_home_page():
    from src.scrapers.plugins.torso import TorsoScraper as S

    scraper = S()
    asked = _stub_fetch(scraper, {D + "/": HOME, D + "/t1/changelog/": T1, D + "/s4/changelog/": S4})

    devices = {d.name: (d.category, d.firmware_page_url) for d in (await scraper.fetch_device_list()).devices}
    s4 = await scraper.fetch_firmware_versions("S-4", devices["S-4"][1])

    assert devices == {"T-1": ("midi_controller", D + "/t1/changelog/"), "S-4": ("synthesizer", D + "/s4/changelog/")}
    assert s4.firmware_versions[0].version == "2.2.0"
    assert len(asked) == 3


@pytest.mark.asyncio
async def test_torso_fails_loudly_without_the_docs_site():
    from src.scrapers.plugins.torso import TorsoScraper as S

    scraper = S()
    _stub_fetch(scraper, {})

    assert (await scraper.fetch_device_list()).success is False
