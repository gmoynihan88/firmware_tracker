import pytest


# The downloads every support page repeats under the product's own.
SHARED_ROWS = """
<tr bgcolor="white"><td class="dash"></td><td class="dash"><b><a href="/?a=dl&amp;b=120" title=" Seven_VeniceGrandCB1898.zip - April 04, 2024 ">Sample Expansion - Venice Grand CB1898</a> - 187,80 Mb</b></td></tr>
<tr bgcolor="#fbfbfb"><td class="dash"></td><td class="dash"><b><a href="/?a=dl&amp;b=60" title=" GSi_Crumar_Midi_driver.exe - July 27, 2020 ">Crumar Midi USB multi-client Windows driver v.2.0.0.0</a> - 1,2 Mb</b></td></tr>
<tr bgcolor="white"><td class="dash"></td><td class="dash"><b><a href="/?a=dl&amp;b=90" title=" WARRANTY_EULA.pdf - January 13, 2023 ">WARRANTY AGREEMENT AND SOFTWARE EULA</a> - 99 Kb</b></td></tr>
"""


def _support_page(label, rows):
    body = "".join(
        f'<tr bgcolor="#fbfbfb"><td class="dash"></td><td class="dash"><b>'
        f'<a href="/?a=dl&amp;b={i}" title=" {title} ">{text}</a> - 1,62 Mb</b>\n'
        f'</td><td class="dash"> <a href="?a=showproduct&amp;b=34">Product page</a></td></tr>'
        for i, (text, title) in enumerate(rows, start=100)
    )
    return (
        '<table border="0" cellpadding="5" cellspacing="0" width="1000"><tr><td align="center">'
        f'</td></tr><tr><td colspan="100%"><b>{label}</b></td></tr>{body}{SHARED_ROWS}</table>'
    )


INDEX = """
<a href="/?a=support&amp;b=34">MOJO61</a>
<a href="/?a=support&amp;b=36">Seven</a>
<a href="/?a=support&amp;b=40">Eleven</a>
<a href="/?a=support&amp;b=46">DK61</a>
<a href="/?a=showproduct&amp;b=34">MOJO61</a>
"""

PAGES = {
    "https://www.crumar.it/?a=support": INDEX,
    "https://www.crumar.it/?a=support&b=34": _support_page("MOJO61", [
        ("Mojo 61 - Firmware Update v.1.53", "Crumar_Mojo61_Update_v1.53.zip - November 27, 2024"),
        ("Mojo 61 - Piano Update - READ THE PDF!", "Mojo61_VeniceGrandCFX.zip - March 30, 2023"),
        ("Mojo 61 - Quick Guide", "Mojo61_Quick_guide_2020.pdf - October 07, 2020"),
    ]),
    "https://www.crumar.it/?a=support&b=36": _support_page("Seven", [
        ("Seven - Firmware v.1.37", "Crumar_Seven_Update_v1.37.zip - May 16, 2022"),
    ]),
    "https://www.crumar.it/?a=support&b=40": _support_page("Eleven", [
        ("Eleven - Documentation", "Crumar_Eleven.pdf - October 28, 2020"),
    ]),
    "https://www.crumar.it/?a=support&b=46": _support_page("DK61", [
        ("DK61 - Firmware updater v.1.0.1", "Crumar_DK61_Updater_V101.zip - February 14, 2026"),
    ]),
}


def _scraper(pages=PAGES):
    from src.scrapers.plugins.crumar import CrumarScraper

    scraper = CrumarScraper()
    fetched = []

    async def _page(url, *_args, **_kwargs):
        fetched.append(url)
        return pages.get(url)

    scraper.fetch_page = _page
    return scraper, fetched


@pytest.mark.asyncio
async def test_crumar_lists_the_products_that_offer_firmware():
    """Eleven offers a manual only, so listing it would add a row that never reports."""
    scraper, _ = _scraper()

    result = await scraper.fetch_device_list()

    assert result.success is True
    devices = {d.name: d for d in result.devices}
    assert list(devices) == ["Mojo 61", "Seven", "DK61"]
    assert devices["Seven"].firmware_page_url == "https://www.crumar.it/?a=support&b=36"
    assert devices["Seven"].product_url == "https://www.crumar.it/?a=showproduct&b=36"


@pytest.mark.asyncio
async def test_crumar_ignores_the_driver_and_sample_sets_every_page_repeats():
    """The Windows MIDI driver is v.2.0.0.0 and the piano sample set says "Update"."""
    scraper, _ = _scraper()

    result = await scraper.fetch_firmware_versions("Mojo 61", "https://www.crumar.it/?a=support&b=34")

    assert result.success is True
    assert [fw.version for fw in result.firmware_versions] == ["1.53"]
    firmware = result.firmware_versions[0]
    assert firmware.release_date.strftime("%Y-%m-%d") == "2024-11-27"
    assert firmware.download_url == "https://www.crumar.it/?a=dl&b=100"


@pytest.mark.asyncio
async def test_crumar_reads_a_dotless_file_version_from_the_link_text():
    """Crumar_DK61_Updater_V101.zip is 1.0.1, which the link text states outright."""
    scraper, _ = _scraper()

    result = await scraper.fetch_firmware_versions("DK61", "https://www.crumar.it/?a=support&b=46")

    assert [fw.version for fw in result.firmware_versions] == ["1.0.1"]


def test_crumar_trusts_the_file_name_over_stale_link_text():
    from src.scrapers.plugins.crumar import CrumarScraper

    page = _support_page("Seven", [
        ("Seven - Firmware v.1.36", "Crumar_Seven_Update_v1.37.zip - May 16, 2022"),
    ])

    assert [fw.version for fw in CrumarScraper()._parse_firmware(page)] == ["1.37"]


@pytest.mark.asyncio
async def test_crumar_keeps_the_databases_name_for_mojo_61():
    scraper, _ = _scraper()

    names = [d.name for d in (await scraper.fetch_device_list()).devices]

    assert "Mojo 61" in names and "MOJO61" not in names


@pytest.mark.asyncio
async def test_crumar_reads_every_page_once_per_scrape():
    scraper, fetched = _scraper()

    await scraper.fetch_device_list()
    for name in ("Mojo 61", "Seven", "DK61"):
        await scraper.fetch_firmware_versions(name, "")

    assert sorted(fetched) == sorted(PAGES)


@pytest.mark.asyncio
async def test_crumar_fails_rather_than_dropping_a_product_whose_page_did_not_load():
    pages = dict(PAGES)
    del pages["https://www.crumar.it/?a=support&b=36"]
    scraper, _ = _scraper(pages)

    assert (await scraper.fetch_device_list()).success is False
    assert (await scraper.fetch_firmware_versions("Seven", "")).success is False

    empty_index, _ = _scraper({"https://www.crumar.it/?a=support": "<p>Support</p>"})
    assert (await empty_index.fetch_device_list()).success is False


@pytest.mark.asyncio
async def test_crumar_reports_no_firmware_for_a_catalogued_product_off_the_index():
    """D9-X and Mojo Desktop keep rows from the old hand-kept list."""
    scraper, _ = _scraper()

    result = await scraper.fetch_firmware_versions("D9-X", "https://github.com/ZioGuido/GMLAB_D9X")

    assert result.success is True
    assert result.firmware_versions == []
