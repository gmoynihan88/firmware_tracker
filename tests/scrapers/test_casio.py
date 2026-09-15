import pytest


def _link(pid, text):
    return (
        f'<div class="column--2"><a href="./download.php?cid=008&amp;pid={pid}">'
        f'<p><span class="icon icon-ah-r-grey-deep"></span>\n\t\t\t\t\t\t\t\t\t\t{text}\n\t\t\t\t\t\t\t\t\t</p></a></div>'
    )


# As served: every heading on the page, firmware or not, inside one <section>.
INDEX = f"""
<section>
<h2 class="t-size-large underline">Firmware Update</h2>
<div><h3 class="t-size-small title-side">Digital Pianos</h3><p class="small"></p></div>
<div class="grid-w--3 frame">
{_link(435, 'PX-5S Version 1.13 - <font color="#333333">Oct. 2014</font>')}
{_link(2629, 'PX-560M Version 1.16 - <font color="#333333">Mar. 2020</font>')}
</div>
<div><h3 class="t-size-small title-side">Keyboards</h3><p class="small"></p></div>
<div class="grid-w--3 frame">{_link(2914, 'CT-S500 Version 1.06')}</div>
<h2 class="t-size-large underline">PC Application</h2>
<div><h3 class="t-size-small title-side">Data Editor</h3></div>
<div class="grid-w--3 frame">{_link(58, 'Data Editor for PX-5S Version 1.0.1 - Sep 2013')}</div>
<h2 class="t-size-large underline">Drivers</h2>
<div class="grid-w--3 frame">{_link(593, 'XW-J1 Driver for Windows7 Version 1.67 - Sep 2013')}</div>
</section>
"""


def _model_page(title, date, rows):
    date_block = f'<div style="text-align: right"><p>{date}</p></div>' if date else ""
    body = "".join(
        f'<tr><td colspan="5" style="text-align: left"><strong><font face="Arial" size="2">{row}<br/></font></strong></td><td></td></tr>'
        if row.startswith("Version") else
        f'<tr><td></td><td style="text-align: left;">{row}</td><td></td><td colspan="2"></td></tr>'
        for row in rows
    )
    return f"""
    <div class="page-head"><div class="grid-w-1 grid-w--1"><div class="column">
    <h1 class="t-size-xx-large">[Firmware Update] {title}</h1></div></div></div>
    <div class="grid-mix grid-1 grid--3 narrow-wrap bg--white">
    <div class="column column-main corporate-detail"><div class="column column-sub bg-white">
    {date_block}
    <div><h2 class="t-size-large underline">Supported Models</h2> PX-5S </div>
    <table border="0" cellpadding="0" cellspacing="0" width="100%"><tbody>
    <tr><td colspan="5"><div class="h2_type201"><h2 class="t-size-large underline">Improvements Provided by This Update</h2></div></td></tr>
    {body}
    </tbody></table></div></div></div>
    """


PAGES = {
    "https://support.casio.com/en/support/download.php?cid=008&pid=20": INDEX,
    "https://support.casio.com/en/support/download.php?cid=008&pid=435": _model_page(
        "PX-5S - Version 1.13", "Oct. 2014",
        ["Version 1.12 >> Version 1.13", "• Improving the process of the sound generator",
         "Version 1.11 >> Version 1.12", "• Improving certain operation."],
    ),
    # Dated on the index only.
    "https://support.casio.com/en/support/download.php?cid=008&pid=2629": _model_page(
        "PX-560M - Version 1.16", None,
        ["Version 1.15 >> Version 1.16", "･ Improving certain operation.",
         "Version 1.8 >> Version 1.9", "･ Improving expression pedal performance."],
    ),
    "https://support.casio.com/en/support/download.php?cid=008&pid=2914": _model_page(
        "CT-S500 - Version 1.06", None,
        ["Version 1.0x >> Version 1.06", "• Improvements to some operations"],
    ),
}


def _scraper(pages=PAGES):
    from src.scrapers.plugins.casio import CasioScraper

    scraper = CasioScraper()
    fetched = []

    async def _page(url, *_args, **_kwargs):
        fetched.append(url)
        return pages.get(url)

    scraper.fetch_page = _page
    return scraper, fetched


def test_casio_reads_only_the_firmware_update_section():
    """The same page lists data editors and drivers with versions of their own."""
    from src.scrapers.plugins.casio import CasioScraper

    models = CasioScraper()._index_models(INDEX)

    assert [(m["name"], m["version"]) for m in models] == [("PX-5S", "1.13"), ("PX-560M", "1.16"), ("CT-S500", "1.06")]
    assert models[0]["date"].strftime("%Y-%m") == "2014-10"
    assert models[1]["date"].strftime("%Y-%m") == "2020-03"
    assert models[2]["date"] is None
    assert models[0]["url"] == "https://support.casio.com/en/support/download.php?cid=008&pid=435"


def test_casio_keeps_each_updates_target_version_with_its_notes():
    from src.scrapers.plugins.casio import CasioScraper

    versions = CasioScraper()._parse_model_page(PAGES["https://support.casio.com/en/support/download.php?cid=008&pid=435"])

    assert [fw.version for fw in versions] == ["1.13", "1.12"]
    assert versions[0].release_date.strftime("%Y-%m") == "2014-10"
    assert versions[1].release_date is None
    assert "sound generator" in versions[0].changelog
    # 1.11 is only ever updated *from*; nothing says it was a published release.
    assert "certain operation" in versions[1].changelog


def test_casio_does_not_read_a_from_version_as_a_release():
    """CT-S500 writes "Version 1.0x >> Version 1.06"."""
    from src.scrapers.plugins.casio import CasioScraper

    versions = CasioScraper()._parse_model_page(PAGES["https://support.casio.com/en/support/download.php?cid=008&pid=2914"])

    assert [fw.version for fw in versions] == ["1.06"]


@pytest.mark.asyncio
async def test_casio_lists_every_model_and_dates_from_the_index_when_the_page_does_not():
    scraper, _ = _scraper()

    devices = {d.name: d for d in (await scraper.fetch_device_list()).devices}

    assert list(devices) == ["PX-5S", "PX-560M", "CT-S500"]
    assert all(d.category == "synthesizer" for d in devices.values())
    px = await scraper.fetch_firmware_versions("PX-560M", devices["PX-560M"].firmware_page_url)
    # Numeric order: 1.16 is newer than 1.9, which comparing the text reverses.
    assert [fw.version for fw in px.firmware_versions] == ["1.16", "1.9"]
    # The page gives no date; the index does.
    assert px.firmware_versions[0].release_date.strftime("%Y-%m") == "2020-03"
    assert px.firmware_versions[1].release_date is None


@pytest.mark.asyncio
async def test_casio_reads_each_page_once_per_scrape():
    scraper, fetched = _scraper()

    listing = await scraper.fetch_device_list()
    for device in listing.devices:
        await scraper.fetch_firmware_versions(device.name, device.firmware_page_url)

    assert sorted(fetched) == sorted(PAGES)


@pytest.mark.asyncio
async def test_casio_fails_loudly():
    missing = dict(PAGES)
    del missing["https://support.casio.com/en/support/download.php?cid=008&pid=2914"]
    assert (await _scraper(missing)[0].fetch_device_list()).success is False

    no_section = {"https://support.casio.com/en/support/download.php?cid=008&pid=20": "<section><h2>Drivers</h2></section>"}
    assert (await _scraper(no_section)[0].fetch_device_list()).success is False

    scraper, _ = _scraper()
    assert (await scraper.fetch_firmware_versions("PX-S7000", "")).success is False
