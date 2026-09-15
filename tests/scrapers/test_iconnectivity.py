import pytest


def _iconn_page() -> str:
    """The firmware grid, the driver grid below it, and the manuals above.

    mioXL's cell carries the zero-width no-break space the real page has: a parser
    that dropped blank-looking cells from one column would shift every later row.
    """
    return """
    <h3>Manuals</h3>
    <div class="row"><div class="col"><p>mioXL</p></div>
      <div class="col"><p>Owner's manual version 1.3</p></div></div>

    <h3>Firmware</h3>
    <div class="row">
      <div class="col"><strong>Product</strong>
        <p>PlayAUDIO2U</p><p>mioXL ﻿</p><p>iConnectMIDI4+</p></div>
      <div class="col"><strong>Version &amp; Date</strong>
        <p>Version 1.0.3 - Aug 19, 2026</p>
        <p>Version 2.4.1 - Aug 17, 2025</p>
        <p>Version 2.2.1 - Jan 20, 2021</p></div>
      <div class="col"><strong>Release Notes</strong>
        <p>Release Notes</p><p>Release Notes</p><p>Release Notes</p></div>
    </div>

    <h3>Windows Drivers</h3>
    <div class="row">
      <div class="col"><p>Unified USB driver for all current iConnectivity products</p></div>
      <div class="col"><p>Version 6.0 - Dec 2, 2025</p></div>
    </div>
    """


def test_iconnectivity_zips_the_product_and_version_columns():
    from src.scrapers.plugins.iconnectivity import IConnectivityScraper as IC

    grid = IC()._parse_grid(_iconn_page())

    assert grid["PlayAUDIO2U"].version == "1.0.3"
    assert grid["mioXL"].version == "2.4.1"
    assert grid["iConnectMIDI4+"].version == "2.2.1"
    assert grid["PlayAUDIO2U"].release_date.strftime("%Y-%m-%d") == "2026-08-19"


def test_iconnectivity_strips_the_zero_width_space_from_a_name():
    """"mioXL ﻿" would be a second row beside anyone's "mioXL"."""
    from src.scrapers.plugins.iconnectivity import IConnectivityScraper as IC

    grid = IC()._parse_grid(_iconn_page())

    assert "mioXL" in grid
    assert not any("﻿" in name for name in grid)


def test_iconnectivity_skips_the_driver_grid():
    """Identical shape, one heading away: "Unified USB driver ... Version 6.0"."""
    from src.scrapers.plugins.iconnectivity import IConnectivityScraper as IC

    grid = IC()._parse_grid(_iconn_page())

    assert not any("driver" in name.lower() for name in grid)
    assert "6.0" not in {fw.version for fw in grid.values()}


def test_iconnectivity_ignores_the_manual_revisions():
    """Twenty-odd "Owner's manual version 1.3" entries sit above the firmware grid."""
    from src.scrapers.plugins.iconnectivity import IConnectivityScraper as IC

    grid = IC()._parse_grid(_iconn_page())

    assert set(grid) == {"PlayAUDIO2U", "mioXL", "iConnectMIDI4+"}
    assert "1.3" not in {fw.version for fw in grid.values()}


def _iconn_scraper(page):
    from src.scrapers.plugins.iconnectivity import IConnectivityScraper as IC

    scraper = IC()
    asked = []

    async def fake_fetch(url, **kwargs):
        asked.append(url)
        return page

    scraper.fetch_page = fake_fetch
    return scraper, asked


@pytest.mark.asyncio
async def test_iconnectivity_reads_the_page_once_for_the_whole_catalogue():
    """One page holds every product, so the firmware pass must not refetch it."""
    scraper, asked = _iconn_scraper(_iconn_page())

    devices = await scraper.fetch_device_list()
    await scraper.fetch_firmware_versions("mioXL", "")
    await scraper.fetch_firmware_versions("PlayAUDIO2U", "")

    assert [d.name for d in devices.devices] == ["PlayAUDIO2U", "iConnectMIDI4+", "mioXL"]
    assert len(asked) == 1


@pytest.mark.asyncio
async def test_iconnectivity_categorises_audio_and_midi_products():
    scraper, _ = _iconn_scraper(_iconn_page())
    devices = await scraper.fetch_device_list()
    by_name = {d.name: d.category for d in devices.devices}

    assert by_name["PlayAUDIO2U"] == "audio_interface"
    assert by_name["iConnectMIDI4+"] == "midi_controller"


@pytest.mark.asyncio
async def test_iconnectivity_fails_when_the_grid_is_gone():
    """A page that loads with no firmware grid means the layout moved.

    Reporting success with nothing would empty iConnectivity from the catalogue's
    view the day Squarespace changes its column classes.
    """
    scraper, _ = _iconn_scraper("<h3>Firmware</h3><p>coming soon</p>")
    result = await scraper.fetch_device_list()

    assert result.success is False

    unreachable, _ = _iconn_scraper(None)
    assert (await unreachable.fetch_device_list()).success is False


@pytest.mark.asyncio
async def test_iconnectivity_reports_a_withdrawn_product_as_an_absence():
    scraper, _ = _iconn_scraper(_iconn_page())
    result = await scraper.fetch_firmware_versions("Discontinued Thing", "")

    assert result.success is True
    assert result.firmware_versions == []
