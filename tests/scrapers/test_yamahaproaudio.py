import pytest

SITE = "https://usa.yamaha.com"
MIXERS = f"{SITE}/products/proaudio/mixers"

INDEX = (
    '<a href="/products/proaudio/mixers/tf/index.html" class="display-block">TF</a>'
    '<a href="/products/proaudio/mixers/dm7/index.html" class="item-link">DM7</a>'
    '<a href="/products/proaudio/mixers/dm7/index.html" class="display-block">DM7</a>'
    '<a href="/products/proaudio/mixers/rivage_pm/index.html" class="display-block">RIVAGE PM</a>'
    '<a href="/products/proaudio/mixers/mgx/index.html" class="display-block">MGX</a>'
)


def _current(label, href, size="20.6MB", stamp="2026-02-12"):
    return (
        f'<tr data-id="1" data-os="-">\n<td>\n<a href="{href}">{label}<span aria-label="Download" class="fa fa-fw fa-download"></span></a> </td>\n'
        f"<td>-</td>\n<td>{size}</td>\n<td>{stamp}</td>\n</tr>"
    )


def _table(*rows):
    return (
        '<table class="table"><tr><th>Name</th><th>OS</th><th>Size</th><th>Last Update</th></tr>'
        + "".join(rows) + "</table>"
    )


def _previous(line, *links):
    items = "".join(
        f'<li> <a href="{href}" target="_blank">{label} <span aria-hidden="true" class="fa fa-fw fa-external-link"></span></a> </li>'
        for label, href in links
    )
    return (
        '<div class="container-fluid"><div class="row grid"><section class="ngc col-xs-12 col-sm-4 previous_ver_heading">'
        '<header><a aria-expanded="false" class="collapse-header" data-toggle="collapse" role="button">'
        f'<h3 class="heading">{line}</h3></a></header><div class="collapse"><ul class="list-unstyled links">'
        '<li> <a href="https://download.yamaha.com/files/tcm:39-1189926" target="_blank"> Previous versions information </a> </li>'
        f"{items}</ul></div></section></div></div>"
    )


TF = (
    _table(
        _current("TF5/3/1 TF-RACK Firmware V4.56", "/support/updates/tf531_tf_rack_firm.html", "157.1MB", "2025-06-04"),
        _current("Tio1608-D2, Tio1608-D Firmware V2.00", "/support/updates/tio1608-d_firm.html", "17.3MB", "2023-08-22"),
        _current("TF Editor V4.5.0 for Mac", "/support/updates/tf_editor_mac.html", "80MB", "2025-06-04"),
    )
    + _previous(
        "TF5/3/1 TF-RACK Firmware",
        ("TF5/3/1 TF-RACK Firmware V4.55", "/support/updates/tf531_tf_rack_firm_v455.html"),
        ("TF5/3/1 TF-RACK Firmware V3.51-2", "/support/updates/tf531_tf_rack_firm3512.html"),
        # The line's name before TF-RACK joined it.
        ("TF Firmware V2.50-2", "/support/updates/67412_en.html"),
        ("TF Firmware V1.10", "/support/updates/64841_en.html"),
    )
    + _previous(
        "Tio1608-D Firmware",
        ("Tio1608-D Firmware V1.06", "/support/updates/tio1608-d_firm_v106.html"),
        ("Tio1608-D Firmware V1.03-2", "/support/updates/tio1608-d_firm1032.html"),
    )
)

DM7 = _table(
    _current("DM7 Firmware V2.00", "/support/updates/dm7_firm.html", "300MB", "2026-03-10"),
    _current("RMio64-D Firmware V5.85 for updating with R-Remote", "/support/updates/rmio64-d_firm.html", "10MB", "2025-11-18"),
    _current("RMio64-D Firmware V5.85 for updating with RMio64-D Update Program", "/support/updates/rmio64-d_firm_up.html", "10MB", "2025-11-18"),
    _current("Rio3224-D2 Firmware V1.90", "/support/updates/rio3224-d2_firm.html", "12MB", "2025-10-01"),
)

RIVAGE = (
    _table(
        _current("RIVAGE PM Firmware V7.10", "/support/updates/rivage_pm_firm.html", "554.1MB", "2026-07-09"),
        _current("HY144-D Firmware V4.2.3.1_3.1.1", "/support/updates/hy144-d_firm.html", "95MB", "2022-05-19"),
        _current("Rio3224-D2 Firmware V1.90", "/support/updates/rio3224-d2_firm.html", "12MB", "2025-10-01"),
    )
    + _previous("HY144-D Firmware", ("HY144-D Firmware V4.0.11.1_2.0.8", "/support/updates/hy144-d_firm_v40111_208.html"))
)

# The analogue mixers' page lists no firmware.
MGX = _table(_current("MGX Series Owner's Manual", "/files/mgx.pdf", "3MB", "2019-01-01"))

PAGES = {
    f"{MIXERS}/": INDEX,
    f"{MIXERS}/tf/downloads.html": TF,
    f"{MIXERS}/dm7/downloads.html": DM7,
    f"{MIXERS}/rivage_pm/downloads.html": RIVAGE,
    f"{MIXERS}/mgx/downloads.html": MGX,
}


def _scraper(pages=PAGES):
    from src.scrapers.plugins.yamahaproaudio import YamahaProAudioScraper

    scraper = YamahaProAudioScraper()
    fetched = []

    async def _page(url, *_args, **_kwargs):
        fetched.append(url)
        return pages.get(url)

    scraper.fetch_page = _page
    return scraper, fetched


async def _versions(scraper, device):
    result = await scraper.fetch_firmware_versions(device, "")
    assert result.success, result.error
    return result.firmware_versions


def test_yamahaproaudio_expands_the_models_a_line_names():
    from src.scrapers.plugins.yamahaproaudio import YamahaProAudioScraper

    models = YamahaProAudioScraper()._models

    assert models("TF5/3/1 TF-RACK") == ["TF5", "TF3", "TF1", "TF-RACK"]
    assert models("Tio1608-D2, Tio1608-D") == ["Tio1608-D2", "Tio1608-D"]
    assert models("RIVAGE PM") == ["RIVAGE PM"]
    assert models("CL1") == ["CL1"]


@pytest.mark.asyncio
async def test_yamahaproaudio_lists_firmware_not_editors():
    scraper, _ = _scraper()

    listing = await scraper.fetch_device_list()

    assert listing.success is True
    assert sorted(d.name for d in listing.devices) == [
        "DM7", "HY144-D", "RIVAGE PM", "RMio64-D", "Rio3224-D2", "TF-RACK", "TF1", "TF3", "TF5", "Tio1608-D", "Tio1608-D2",
    ]
    tf5 = next(d for d in listing.devices if d.name == "TF5")
    assert tf5.firmware_page_url == f"{SITE}/support/updates/tf531_tf_rack_firm.html"
    assert tf5.product_url == f"{MIXERS}/tf/downloads.html"


@pytest.mark.asyncio
async def test_yamahaproaudio_dates_the_current_row_and_files_previous_versions_under_their_section():
    """"TF Firmware V2.50-2" sits in the TF5/3/1 TF-RACK section, so it is that line's history."""
    scraper, _ = _scraper()

    for model in ("TF5", "TF-RACK"):
        versions = await _versions(scraper, model)
        assert [(fw.version, fw.release_date.strftime("%Y-%m-%d") if fw.release_date else None) for fw in versions] == [
            ("4.56", "2025-06-04"), ("4.55", None), ("3.51-2", None), ("2.50-2", None), ("1.10", None),
        ]
    tio = await _versions(scraper, "Tio1608-D")
    assert [fw.version for fw in tio] == ["2.00", "1.06", "1.03-2"]
    assert [fw.version for fw in await _versions(scraper, "Tio1608-D2")] == ["2.00"]


@pytest.mark.asyncio
async def test_yamahaproaudio_reads_one_release_per_version_across_downloads_and_pages():
    scraper, _ = _scraper()

    rmio = await _versions(scraper, "RMio64-D")
    rio = await _versions(scraper, "Rio3224-D2")
    hy = await _versions(scraper, "HY144-D")

    assert [fw.version for fw in rmio] == ["5.85"]
    assert [fw.version for fw in rio] == ["1.90"]
    assert [(fw.version, fw.release_date is not None) for fw in hy] == [("4.2.3.1_3.1.1", True), ("4.0.11.1_2.0.8", False)]


@pytest.mark.asyncio
async def test_yamahaproaudio_reads_each_page_once():
    scraper, fetched = _scraper()

    listing = await scraper.fetch_device_list()
    for device in listing.devices:
        await scraper.fetch_firmware_versions(device.name, device.firmware_page_url)

    assert sorted(fetched) == sorted(PAGES)


@pytest.mark.asyncio
async def test_yamahaproaudio_fails_loudly():
    assert (await _scraper({})[0].fetch_device_list()).success is False

    no_families = {f"{MIXERS}/": "<p>Maintenance</p>"}
    assert (await _scraper(no_families)[0].fetch_device_list()).success is False

    missing = dict(PAGES)
    del missing[f"{MIXERS}/dm7/downloads.html"]
    assert (await _scraper(missing)[0].fetch_device_list()).success is False

    scraper, _ = _scraper()
    assert (await scraper.fetch_firmware_versions("CL5", "")).success is False
