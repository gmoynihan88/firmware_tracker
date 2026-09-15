import asyncio

import pytest


def test_yamaha_recognises_its_generic_landing_page():
    """Eleven Yamaha product URLs serve the same page an invented slug does.

    Reported as "no firmware", that claims a verified absence where there is a dead
    URL -- the distinction the scrape summary exists to keep.
    """
    from src.scrapers.plugins.yamaha import YamahaScraper

    scraper = YamahaScraper()

    dead = "<html><head><title>Firmware / Software Updates - Yamaha - United States</title></head><body></body></html>"
    live = "<html><head><title>THR Remote V1.6.0 for Mac - Yamaha USA</title></head><body></body></html>"

    assert scraper._is_dead_page(dead) is True
    assert scraper._is_dead_page(live) is False
    # No title at all is not a claim either way, so it is not treated as dead.
    assert scraper._is_dead_page("<html><body>nothing</body></html>") is False


@pytest.mark.asyncio
async def test_yamaha_dead_url_is_a_failure_not_an_absence():
    from src.scrapers.plugins.yamaha import YamahaScraper

    scraper = YamahaScraper()

    async def landing(*args, **kwargs):
        return "<html><head><title>Firmware / Software Updates - Yamaha</title></head></html>"

    scraper.fetch_page = landing
    result = await scraper.fetch_firmware_versions(
        "Montage M6", "https://usa.yamaha.com/support/updates/montagem6_firm.html"
    )

    assert result.success is False
    assert "montagem6_firm" in result.error


def test_yamaha_reads_thr_firmware_from_the_remote_page():
    """The THR-II line's firmware appears as a compatibility note on an app page.

    One note covers all four amps; a second covers the G10T transmitter that ships
    with the wireless model, which is why a Line 6 product is listed under Yamaha.
    """
    from src.scrapers.plugins.yamaha import YamahaScraper

    page = ("<html><body><p>[Firmware Ver.1.50 for THR-II]</p>"
            "<p>[Firmware Ver.1.10 for THR30IIA Wireless]</p></body></html>")
    scraper = YamahaScraper()

    amps = scraper._parse_thr_remote_page(page, "THR30II Wireless")
    transmitter = scraper._parse_thr_remote_page(page, "Line 6 G10TII")

    assert [f.version for f in amps] == ["1.50"]
    assert [f.version for f in transmitter] == ["1.10"]


def test_yamaha_reads_the_os_updater_and_not_the_drivers():
    """The download pages list drivers and file sizes beside the firmware.

    "Yamaha Steinberg USB Driver V2.1.9" is not the instrument's OS, and "3.91GB" is
    a file size. Requiring the word Updater is what separates them.
    """
    from src.scrapers.plugins.yamaha import YamahaScraper

    page = """<html><body>
      <p>MONTAGE M OS Updater V3.01 from earlier versions (3.91GB)</p>
      <p>Yamaha Steinberg USB Driver V2.1.9 for Windows 11/10 (64-bit)</p>
      <p>USB-MIDI Driver V1.3.2-2 for Mac macOS 10.15-OS X 10.5</p>
      <p>[12.9MB]</p>
    </body></html>"""

    versions = YamahaScraper()._parse_updater_page(page)

    assert [f.version for f in versions] == ["3.01"]


def test_yamaha_accepts_a_hyphenated_updater_version():
    """reface updaters are versioned "V1.30-3", which a plain x.y.z pattern truncates."""
    from src.scrapers.plugins.yamaha import YamahaScraper

    page = "<html><body><p>reface CP updater V1.30-3 for Mac</p></body></html>"

    assert [f.version for f in YamahaScraper()._parse_updater_page(page)] == ["1.30-3"]


def test_yamaha_updater_page_with_nothing_to_read_returns_empty():
    """So the caller falls through rather than inventing a version."""
    from src.scrapers.plugins.yamaha import YamahaScraper

    assert YamahaScraper()._parse_updater_page("<html><body><p>no downloads</p></body></html>") == []


def _yamaha_downloads_page() -> str:
    """A downloads table, shaped like the real one.

    Flattened to text this reads "...75.4MB 2026-01-14 Yamaha Steinberg USB Driver
    V2.1.9...", which puts every date immediately before the *next* row's name. That
    is why the scraper recorded no dates for so long and reported there were none.
    The drivers and the editor carry their own versions and their own dates, and a
    pattern that does not require the word Updater takes them.
    """
    return """
    <html><head><title>MONTAGE M Synthesizer Manuals &amp; Software - Yamaha USA</title></head>
    <body><table class="table table-bordered">
      <tr><th>Name</th><th>OS</th><th>Size</th><th>Last Update</th></tr>
      <tr><td>MONTAGE M OS Updater V3.01 from earlier versions (3.91GB)</td>
          <td>-</td><td>&mdash;</td><td>2026-01-14</td></tr>
      <tr><td>MONTAGE M OS Updater V3.01 from version V3.00</td>
          <td>-</td><td>75.4MB</td><td>2026-01-14</td></tr>
      <tr><td>MONTAGE M OS Updater V2.00</td>
          <td>-</td><td>3.8GB</td><td>2024-06-11</td></tr>
      <tr><td>Yamaha Steinberg USB Driver V2.1.9 for Windows 11/10 (64-bit)</td>
          <td>Win</td><td>8.2MB</td><td>2025-06-25</td></tr>
      <tr><td>THR Remote V1.6.0 for Mac</td><td>Mac</td><td>20.3MB</td><td>2025-12-17</td></tr>
    </table></body></html>
    """


def _yamaha_reface_page() -> str:
    """One table covering four products, with CS and DX sharing an updater file."""
    return """
    <html><head><title>reface - Downloads - Synthesizers - Yamaha USA</title></head>
    <body><table class="table table-bordered">
      <tr><th>Name</th><th>OS</th><th>Size</th><th>Last Update</th></tr>
      <tr><td>reface CP updater V1.30-3 for Mac</td><td>Mac</td><td>7.9MB</td><td>2019-10-25</td></tr>
      <tr><td>reface CS/DX updater V1.30-3 for Mac</td><td>Mac</td><td>6.6MB</td><td>2019-10-25</td></tr>
      <tr><td>reface YC updater V1.30-3 for Mac</td><td>Mac</td><td>7.2MB</td><td>2019-10-25</td></tr>
      <tr><td>reface CP updater V1.30 for Windows</td><td>Win</td><td>9.5MB</td><td>2016-04-07</td></tr>
      <tr><td>reface CS/DX updater V1.20 for Win</td><td>Win</td><td>12.9MB</td><td>2015-09-01</td></tr>
    </table></body></html>
    """


def test_yamaha_pairs_each_version_with_its_own_rows_date():
    """The date is in the row's own cell, not the text that follows it."""
    from src.scrapers.plugins.yamaha import YamahaScraper

    versions = YamahaScraper()._parse_downloads_table(
        _yamaha_downloads_page(), "Montage M8x"
    )

    assert [(fw.version, fw.release_date.strftime("%Y-%m-%d")) for fw in versions] == [
        ("3.01", "2026-01-14"),
        ("2.00", "2024-06-11"),
    ]


def test_yamaha_ignores_the_drivers_and_the_editor_sharing_the_table():
    """Each carries a version and a date of its own, and neither is the instrument's.

    THR Remote is the trap worth naming: it is dated, it is on the amp's own
    downloads page, and its numbering runs on a different track from the amp's.
    """
    from src.scrapers.plugins.yamaha import YamahaScraper

    versions = YamahaScraper()._parse_downloads_table(
        _yamaha_downloads_page(), "Montage M8x"
    )
    found = {fw.version for fw in versions}

    assert "2.1.9" not in found, "took the USB driver"
    assert "1.6.0" not in found, "took the THR Remote editor"


def test_yamaha_reads_a_shared_updater_for_both_products():
    """reface CS/DX is one file for two instruments, and CP must not collect it."""
    from src.scrapers.plugins.yamaha import YamahaScraper

    scraper = YamahaScraper()
    page = _yamaha_reface_page()

    cs = {fw.version for fw in scraper._parse_downloads_table(page, "reface CS")}
    dx = {fw.version for fw in scraper._parse_downloads_table(page, "reface DX")}
    cp = {fw.version for fw in scraper._parse_downloads_table(page, "reface CP")}

    assert cs == dx == {"1.30-3", "1.20"}
    assert cp == {"1.30-3", "1.30"}
    assert "1.20" not in cp, "CP collected the CS/DX updater"


def test_yamaha_sorts_newest_first_with_a_suffixed_version():
    """The table is ordered by platform, so "1.30-3" has to sort above "1.30"."""
    from src.scrapers.plugins.yamaha import YamahaScraper

    versions = YamahaScraper()._parse_downloads_table(_yamaha_reface_page(), "reface CP")

    assert [fw.version for fw in versions] == ["1.30-3", "1.30"]


def test_yamaha_invents_nothing_when_the_table_is_gone():
    """The free-text fallback that used to stand here would scan this and find 10.15.

    An honest empty renders as "Firmware Unknown" and prompts a look. A version
    taken off an OS requirement is a green tick that stops anyone looking.
    """
    import asyncio

    from src.scrapers.plugins.yamaha import YamahaScraper

    page = """<html><head><title>MODX Manuals &amp; Software - Yamaha USA</title></head>
        <body><p>Requires macOS 10.15 or above. Download size 12.9MB.
        See Firmware Ver.9.99 for details.</p></body></html>"""

    scraper = YamahaScraper()
    assert scraper._parse_downloads_table(page, "MODX8") == []

    async def run():
        async def fake_fetch(url, **kwargs):
            return page

        scraper.fetch_page = fake_fetch
        return await scraper.fetch_firmware_versions(
            "MODX8", "https://usa.yamaha.com/products/x/downloads.html"
        )

    result = asyncio.run(run())
    assert result.success is True
    assert result.firmware_versions == []
