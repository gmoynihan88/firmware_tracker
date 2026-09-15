from datetime import datetime

import pytest

from tests.support import _stub_fetch


def _release(os_name, version, date, notes_html, video=False, path=None):
    stamp = f'<span class="smallfont">{date}<br/></span>' if date is not None else ""
    player = ('<p><div style="width:280px;height:155px"><section class="n_T"><div class="n_S">'
              '<img class="n_V" alt="Video" src="https://img.youtube.com/vi/x/sddefault.jpg"/></div></section></div></p>'
              if video else "")
    link = f'<p><a class="downloadOS" href="{path}" download="">Download <!-- -->{os_name}<!-- --> <!-- -->{version}</a></p>' if path else ""
    return (f'<p class="Headline_grey">{os_name}<!-- --> <!-- -->{version}<br/>{stamp}</p>'
            f'{player}' + (f'<div class="mini_Text_grey">{notes_html}</div>' if notes_html is not None else '')
            + f'{link} <div class="Line"></div>')


def _page(*releases):
    return (
        '<html><body><div><h3 class="MuiAccordion-heading">🇯🇵 ▼</h3></div>'
        '<div class="Box_PyraOs"><div class="Headline">' + "".join(releases) + "</div></div></body></html>"
    )


HAPAX = _page(
    _release("HapaxOS", "3.20", "September 10, 2026",
             "New features<ul><li>Sync In — CV Follow Tempo</li></ul>Bug fixes<ul><li>LFO: fixed a freeze.</li></ul>",
             path="/hapaxOS/3.20/hapax.bin"),
    _release("HapaxOS", "3.10", "June 18, 2026", "Bug fixes<ul><li>Track type fixes.</li></ul>", path="/hapaxOS/3.10/hapax.bin"),
)
RAMPLE = _page(
    _release("rampleOS", "3.00", "Feb 27, 2026", "Effects<ul><li>New Compressor master FX.</li></ul>", path="/rampleOS/300/rample.bin"),
    _release("rampleOS", "2.00", "Feb 15, 2024", "Breaking changes<ul><li>Latency greatly improved</li></ul>",
             video=True, path="/rampleOS/200/rample.bin"),
    _release("rampleOS", "1.0", "27 January 2020", "First release"),
)
PYRAMID = _page(
    _release("PyraOS", "4.03", "october 10, 2023", None),
    _release("PyraOS", "0.78", "july 10, 2015", "<ul><li>First beta</li></ul>"),
)
HERMODPLUS = _page(
    _release("Hermod+OS", "2.00", "February 03, 2025", "<ul><li>New mute behaviour</li></ul>"),
    _release("Hermod+OS", "1.021", None, "<ul><li>Hotfix</li></ul>"),
)

B = "https://squarp.net"
HOME = (
    '<html><body><a href="/hapax/">Hapax</a><a href="/hapax/firmware/">firmware</a><a href="/hapax/manual/">manual</a>'
    '<a href="/hermodplus/firmware/">firmware</a><a href="/rample/firmware/">firmware</a><a href="/hapax/firmware/">again</a>'
    '<a href="/legacy/">legacy</a><a href="/static/HAPAX_QUICKSTART_FR.pdf">quickstart</a></body></html>'
)
LEGACY = (
    '<html><body><a href="/hermodplus/firmware/">Hermod+</a><a href="/legacy/pyramid/firmware/">firmware</a>'
    '<a href="/legacy/pyramid/manual/">manual</a></body></html>'
)


def test_squarp_pairs_each_version_with_its_own_date_and_notes():
    from src.scrapers.plugins.squarp import SquarpScraper

    releases = SquarpScraper()._parse_page(HAPAX)

    assert [(r.version, r.release_date) for r in releases] == [
        ("3.20", datetime(2026, 9, 10)), ("3.10", datetime(2026, 6, 18)),
    ]
    assert releases[0].changelog == "New features\nSync In — CV Follow Tempo\nBug fixes\nLFO: fixed a freeze."


def test_squarp_reads_every_date_shape():
    from src.scrapers.plugins.squarp import SquarpScraper

    scraper = SquarpScraper()

    assert [r.release_date for r in scraper._parse_page(RAMPLE)] == [
        datetime(2026, 2, 27), datetime(2024, 2, 15), datetime(2020, 1, 27),
    ]
    assert [(r.release_date, r.changelog) for r in scraper._parse_page(PYRAMID)] == [
        (datetime(2023, 10, 10), None), (datetime(2015, 7, 10), "First beta"),
    ]
    assert [(r.version, r.release_date) for r in scraper._parse_page(HERMODPLUS)] == [
        ("2.00", datetime(2025, 2, 3)), ("1.021", None),
    ]


def test_squarp_notes_skip_an_embedded_video():
    from src.scrapers.plugins.squarp import SquarpScraper

    assert SquarpScraper()._parse_page(RAMPLE)[1].changelog == "Breaking changes\nLatency greatly improved"


@pytest.mark.asyncio
async def test_squarp_names_products_from_their_firmware_page_paths():
    from src.scrapers.plugins.squarp import SquarpScraper as S

    scraper = S()
    asked = _stub_fetch(scraper, {
        B + "/": HOME, S.LEGACY_URL: LEGACY,
        B + "/hapax/firmware/": HAPAX, B + "/hermodplus/firmware/": HERMODPLUS,
        B + "/rample/firmware/": RAMPLE, B + "/legacy/pyramid/firmware/": PYRAMID,
    })

    devices = {d.name: (d.category, d.firmware_page_url) for d in (await scraper.fetch_device_list()).devices}
    pyramid = await scraper.fetch_firmware_versions("Pyramid", devices["Pyramid"][1])

    assert devices == {
        "Hapax": ("midi_controller", B + "/hapax/firmware/"),
        "Hermod+": ("midi_controller", B + "/hermodplus/firmware/"),
        "Rample": ("synthesizer", B + "/rample/firmware/"),
        "Pyramid": ("midi_controller", B + "/legacy/pyramid/firmware/"),
    }
    assert [r.version for r in pyramid.firmware_versions] == ["4.03", "0.78"]
    assert len(asked) == 6


@pytest.mark.asyncio
async def test_squarp_fails_loudly_without_the_home_page():
    from src.scrapers.plugins.squarp import SquarpScraper as S

    scraper = S()
    _stub_fetch(scraper, {})

    assert (await scraper.fetch_device_list()).success is False
