from datetime import datetime

import pytest

from tests.support import _stub_fetch

FILTER = (
    '<form action="https://www.xlnaudio.com/release_notes" id="listReleaseNotes" method="GET">'
    '<label>Filter:\n                        <select autofocus="" name="filter" onchange="this.form.submit()">'
    '<option value="all">All Products</option>'
    '<option value="addictive_drums">Addictive\n                                Drums</option>'
    '<option value="life">Life</option>'
    '<option value="online_installer">XLN\n                                Online Installer</option>'
    '<option value="xo">XO</option>'
    "</select></label></form>"
)


def _row(product, version, notes, date):
    return (
        '<tr class="align-top even:bg-surface-secondary">'
        f'<td class="px-2 py-4">\n                                         {product}                                     </td>'
        f'<td class="px-2 py-4">{version}</td>'
        f'<td class="prose prose-ul:ml-0 px-2 py-4">{notes}</td>'
        f'<td class="px-2 py-4">{date}</td></tr>'
    )


def _page(*rows, with_filter=True):
    return (
        "<html><body>" + (FILTER if with_filter else "")
        + '<div class="relative overflow-x-auto"><table class="w-full table-auto text-left">'
        '<thead><tr><th>Product</th><th>Version</th><th>Release Notes</th><th>Release Date</th></tr></thead>'
        "<tbody>" + "".join(rows) + "</tbody></table></div></body></html>"
    )


PAGE_1 = _page(
    _row("XLN Online Installer", "4.7.3", "<ul> <li>Fixed showing rent-to-own badge on XO</li> </ul> ", "Aug 18, 2026"),
    _row("XO", "1.8.10", "<ul> <li>Fixed a bug when exporting MIDI with lanes muted</li> "
                         "<li>Fixed an issue when exporting audio while playing in the host</li> </ul>", "Aug 7, 2026"),
    _row("Phonk", "1.0.1", "Initial build", "Sep 4, 2026"),
)
PAGE_2 = _page(
    _row("Addictive Drums 2", "2.9.1", "<p>Bugfixes and performance improvements</p>", "Apr 28, 2026"),
    _row("Life DAW Recorder", "1.2.0", "1.2 Release build", "Mar 18, 2025"),
    _row("XO", "1.7.6", "<ul><li>Fixed issue with start-up preset</li></ul>", "Sept 10, 2025"),
    with_filter=False,
)
EMPTY = _page(with_filter=False)


def test_xlnaudio_reads_version_date_and_notes_from_each_row():
    from src.scrapers.plugins.xlnaudio import XLNAudioScraper

    rows = XLNAudioScraper()._parse_rows(PAGE_1 + PAGE_2)

    assert [(name, fw.version, fw.release_date) for name, fw in rows][:2] == [
        ("XLN Online Installer", "4.7.3", datetime(2026, 8, 18)), ("XO", "1.8.10", datetime(2026, 8, 7)),
    ]
    assert rows[1][1].changelog == (
        "Fixed a bug when exporting MIDI with lanes muted\nFixed an issue when exporting audio while playing in the host"
    )
    assert rows[3][1].changelog == "Bugfixes and performance improvements"
    assert rows[5][1].release_date == datetime(2025, 9, 10)


def test_xlnaudio_keeps_only_filter_products_and_their_generations():
    from src.scrapers.plugins.xlnaudio import XLNAudioScraper as S

    filters = S()._parse_filters(PAGE_1)

    assert filters == {"Addictive Drums": "addictive_drums", "Life": "life",
                       "XLN Online Installer": "online_installer", "XO": "xo"}
    assert [S._filter_for(n, filters) for n in ("Addictive Drums 2", "XO", "Phonk", "Life DAW Recorder")] == [
        "addictive_drums", "xo", None, None,
    ]


@pytest.mark.asyncio
async def test_xlnaudio_reads_every_page_until_one_is_empty():
    from src.scrapers.plugins.xlnaudio import XLNAudioScraper as S

    scraper = S()
    asked = _stub_fetch(scraper, {
        S.RELEASE_NOTES_URL: PAGE_1,
        S.RELEASE_NOTES_URL + "?page=2": PAGE_2,
        S.RELEASE_NOTES_URL + "?page=3": EMPTY,
        S.RELEASE_NOTES_URL + "?page=4": PAGE_2.replace("2.9.1", "2.9.0"),
    })

    devices = {d.name: d.firmware_page_url for d in (await scraper.fetch_device_list()).devices}
    xo = await scraper.fetch_firmware_versions("XO", devices["XO"])

    assert devices == {
        "XLN Online Installer": S.RELEASE_NOTES_URL + "?filter=online_installer",
        "XO": S.RELEASE_NOTES_URL + "?filter=xo",
        "Addictive Drums 2": S.RELEASE_NOTES_URL + "?filter=addictive_drums",
    }
    assert [fw.version for fw in xo.firmware_versions] == ["1.8.10", "1.7.6"]
    assert len(asked) == 3


@pytest.mark.asyncio
async def test_xlnaudio_stops_when_a_page_repeats():
    from src.scrapers.plugins.xlnaudio import XLNAudioScraper as S

    scraper = S()
    asked = _stub_fetch(scraper, {S.RELEASE_NOTES_URL: PAGE_1, **{
        f"{S.RELEASE_NOTES_URL}?page={n}": PAGE_1 for n in range(2, 30)
    }})

    devices = (await scraper.fetch_device_list()).devices

    assert [d.name for d in devices] == ["XLN Online Installer", "XO"]
    assert len(asked) == 2


@pytest.mark.asyncio
async def test_xlnaudio_fails_loudly_without_the_release_notes():
    from src.scrapers.plugins.xlnaudio import XLNAudioScraper as S

    scraper = S()
    _stub_fetch(scraper, {})

    assert (await scraper.fetch_device_list()).success is False
