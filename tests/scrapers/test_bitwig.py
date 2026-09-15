import pytest

from tests.support import _stub_fetch


def _bitwig_table(*rows) -> str:
    """(version, date) pairs, as the release archive lays them out."""
    body = "".join(
        f"<tr><td>{version}</td><td>{date}</td><td></td>"
        f'<td><a href="/x.exe">Windows</a></td><td><a href="/x.dmg">macOS</a></td>'
        f'<td><a href="/notes">Release notes</a></td></tr>'
        for version, date in rows
    )
    return f"<table><tr><th>Version</th><th>Date</th></tr>{body}</table>"


def test_bitwig_reads_version_and_date_from_one_row():
    from src.scrapers.plugins.bitwig import BitwigScraper

    parsed = BitwigScraper()._parse(_bitwig_table(("6.1.1", "Sep 2, 2026")))

    assert [(fw.version, fw.release_date.date().isoformat()) for fw in parsed] == [
        ("6.1.1", "2026-09-02")
    ]


def test_bitwig_sorts_versions_numerically():
    """As strings 6.0.6 sorts above 6.0.11, which is two months backwards."""
    from src.scrapers.plugins.bitwig import BitwigScraper

    parsed = BitwigScraper()._parse(_bitwig_table(
        ("6.0.6", "Apr 30, 2026"),
        ("6.0.11", "Jun 24, 2026"),
        ("6.1", "Aug 26, 2026"),
    ))

    assert [fw.version for fw in parsed] == ["6.1", "6.0.11", "6.0.6"]


def test_bitwig_reads_both_tables_as_one_product():
    """Studio and Studio 1 are one product split by installer, not two lines."""
    from src.scrapers.plugins.bitwig import BitwigScraper

    page = (_bitwig_table(("2.0", "Feb 28, 2017"))
            + "<h2>Download previous releases (Bitwig Studio 1)</h2>"
            + _bitwig_table(("1.3.16", "Mar 15, 2017")))
    parsed = BitwigScraper()._parse(page)

    assert [fw.version for fw in parsed] == ["2.0", "1.3.16"]


def test_bitwig_accepts_a_four_letter_month():
    """"Sept" is what tripped Elektron: the regex took it, strptime would not."""
    from src.scrapers.plugins.bitwig import BitwigScraper

    parsed = BitwigScraper()._parse(_bitwig_table(("5.0", "Sept 9, 2025")))

    assert parsed[0].release_date.date().isoformat() == "2025-09-09"


def test_bitwig_skips_rows_that_are_not_releases():
    from src.scrapers.plugins.bitwig import BitwigScraper

    page = ("<table><tr><th>Version</th><th>Date</th></tr>"
            "<tr><td>Latest stable</td><td>Sep 2, 2026</td></tr></table>")

    assert BitwigScraper()._parse(page) == []


def test_bitwig_leaves_a_release_undated_rather_than_guessing():
    from src.scrapers.plugins.bitwig import BitwigScraper

    parsed = BitwigScraper()._parse(_bitwig_table(("6.1.1", "coming soon")))

    assert parsed[0].version == "6.1.1"
    assert parsed[0].release_date is None


@pytest.mark.asyncio
async def test_bitwig_reads_the_archive_once_for_the_whole_history():
    from src.scrapers.plugins.bitwig import BitwigScraper

    scraper = BitwigScraper()
    asked = _stub_fetch(scraper, {BitwigScraper.RELEASES_URL: _bitwig_table(
        ("6.1.1", "Sep 2, 2026"), ("6.1", "Aug 26, 2026"))})

    devices = await scraper.fetch_device_list()
    result = await scraper.fetch_firmware_versions(
        devices.devices[0].name, devices.devices[0].firmware_page_url
    )

    assert len(asked) == 1
    assert [d.name for d in devices.devices] == ["Bitwig Studio"]
    assert [fw.version for fw in result.firmware_versions] == ["6.1.1", "6.1"]


@pytest.mark.asyncio
async def test_bitwig_fails_loudly_when_the_archive_is_empty():
    """An empty archive is a broken page -- Bitwig always lists 146 releases."""
    from src.scrapers.plugins.bitwig import BitwigScraper

    scraper = BitwigScraper()
    _stub_fetch(scraper, {BitwigScraper.RELEASES_URL: "<p>Log in to continue</p>"})
