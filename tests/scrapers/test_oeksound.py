from datetime import datetime

import pytest

from tests.support import _stub_fetch


def _entry(version, notes, released=None):
    stamp = f'<small class="text-muted mb-2 d-block">Released on {released}</small>' if released else ""
    body = notes if notes.startswith("<p>") else f"<ul>\n{notes}\n</ul>\n"
    return f'<div class="mb-5"><h3>{version}</h3>{stamp}{body}</div>'


def _changelog(title, *entries):
    return (
        '<html><body><header><nav><span class="ms-3 font-mono small">No items in cart.</span></nav></header>'
        '<main class="centered-content" id="main-content"><div class="change-log mt-5"><div class="narrow-content">'
        f'<h2 class="mb-4">{title}</h2>' + "".join(entries) + "</div></div></main>"
        '<div><h3 class="text-center">subscribe to our mailing list</h3><small>We never share your e-mail address.</small></div>'
        "</body></html>"
    )


SOOTHE3 = _changelog(
    "soothe3 change log",
    _entry("1.0.5", "<li>Windows: fix the user interface not rendering correctly on some older graphics cards</li>",
           "June 29, 2026"),
    _entry("1.0.3", "<p>Initial release.</p>\n", "May 19, 2026"),
)
LEGACY_SOOTHE = _changelog(
    "soothe change log",
    _entry("1.4.0", "<li>New features\n<ul>\n<li>undo-redo</li>\n<li>search field</li>\n</ul>\n</li>\n"
                    "<li>Bug fixes\n<ul>\n<li>freeze on <strong>Cubase 10.5</strong> when opening the editor</li>\n</ul>\n</li>\n"
                    "<li>MacOS Catalina compatibility</li>", "March 2, 2020"),
    _entry("1.3.2", "<li>Fixed a rare recall bug in Pro Tools</li>"),
    _entry("1.1.3'", "<li>Fixed a preset recall issue</li>"),
)
SPIFF = _changelog(
    "spiff change log",
    _entry("1.2.0", "<li>New algorithm</li>", "October 5, 2021"),
    _entry("1.0.1b", "<li>additional minor fixes to Windows installer</li>"),
    _entry("1.0.1a", "<li>fixed incorrect VST3 installation paths</li>"),
)

B = "https://oeksound.com"
DOWNLOADS = (
    '<html><body><a href="/plugins/soothe3">soothe3</a><a href="/changelog/soothe3">change log</a>'
    '<a href="https://storage.googleapis.com/oeksound-downloads/soothe2/soothe2_v133_Mac.pkg">macOS</a>'
    '<a href="/changelog/spiff">change log</a><a href="/changelog/soothe3">change log</a>'
    '<a href="/changelog/legacy-soothe">change log</a><a href="/changelog/bloom">change log</a></body></html>'
)


def test_oeksound_pairs_each_version_with_its_own_date_or_none():
    from src.scrapers.plugins.oeksound import OeksoundScraper

    name, releases = OeksoundScraper()._parse_changelog(LEGACY_SOOTHE)

    assert name == "soothe"
    assert [(r.version, r.release_date) for r in releases] == [
        ("1.4.0", datetime(2020, 3, 2)), ("1.3.2", None), ("1.1.3", None),
    ]


def test_oeksound_keeps_letter_revisions_as_written():
    from src.scrapers.plugins.oeksound import OeksoundScraper

    _name, releases = OeksoundScraper()._parse_changelog(SPIFF)

    assert [r.version for r in releases] == ["1.2.0", "1.0.1b", "1.0.1a"]


def test_oeksound_notes_give_nested_items_their_own_lines():
    from src.scrapers.plugins.oeksound import OeksoundScraper

    _name, releases = OeksoundScraper()._parse_changelog(LEGACY_SOOTHE)

    assert releases[0].changelog.splitlines() == [
        "New features", "undo-redo", "search field", "Bug fixes",
        "freeze on Cubase 10.5 when opening the editor", "MacOS Catalina compatibility",
    ]


@pytest.mark.asyncio
async def test_oeksound_reads_every_change_log_the_downloads_page_links():
    from src.scrapers.plugins.oeksound import OeksoundScraper as S

    scraper = S()
    asked = _stub_fetch(scraper, {
        S.DOWNLOADS_URL: DOWNLOADS,
        B + "/changelog/soothe3": SOOTHE3,
        B + "/changelog/spiff": SPIFF,
        B + "/changelog/legacy-soothe": LEGACY_SOOTHE,
    })

    devices = {d.name: d.firmware_page_url for d in (await scraper.fetch_device_list()).devices}
    soothe3 = await scraper.fetch_firmware_versions("soothe3", devices["soothe3"])

    assert devices == {"soothe3": B + "/changelog/soothe3", "spiff": B + "/changelog/spiff",
                       "soothe": B + "/changelog/legacy-soothe"}
    assert [(r.version, r.release_date, r.changelog) for r in soothe3.firmware_versions] == [
        ("1.0.5", datetime(2026, 6, 29),
         "Windows: fix the user interface not rendering correctly on some older graphics cards"),
        ("1.0.3", datetime(2026, 5, 19), "Initial release."),
    ]
    assert len(asked) == 5


@pytest.mark.asyncio
async def test_oeksound_fails_loudly_without_the_downloads_page():
    from src.scrapers.plugins.oeksound import OeksoundScraper as S

    scraper = S()
    _stub_fetch(scraper, {})

    assert (await scraper.fetch_device_list()).success is False
