import pytest


def _latest(rows, heading=True):
    body = "".join(f"<tr><td>{label}</td><td>{version}</td></tr>" for label, version in rows)
    head = "<tr><td>Latest version info</td></tr>" if heading else ""
    return f'<div class="col-md-8 col-sm-11 col-md-offset-2"><table class="table table-bordered">{head}{body}</table></div>'


def _documents(rows):
    body = "".join(
        f'<tr><td></td><th><a href="https://tascam.com/wp-content/uploads/downloads/products/tascam/{i}.zip">{label}</a></th>'
        f'<td class="docs_td">{date}</td><td class="docs_td align-center"></td></tr>'
        for i, (label, date) in enumerate(rows)
    )
    return (
        '<section class="btob-information-wrapper-1" id="Firmware / Software">'
        f'<div class="btob-information-wrapper"><table class="table documents-table m-auto">{body}</table></div></section>'
    )


def _support_page(title, *parts):
    return f"<html><head><title>{title} | TASCAM - United States</title></head><body>{''.join(parts)}</body></html>"


MODEL_12 = _support_page(
    "Model 12 | 12-Track Digital Recording Mixer With DAW Controller & Audio Interface",
    _latest([("Firmware", "V1.50"), ("TASCAM Model Mixer setting panel (Windows)", "V2.20")]),
    _documents([("Release Notes", "2025-06-25"), ("Firmware update procedures", "2020-05-07")]),
    _documents([("Firmware V1.50", "2025-06-25"), ("Firmware V1.42", "2024-06-05")]),
)

CD_400U = _support_page(
    "CD-400U | CD/SD/USB Player with Bluetooth® Receiver and FM/AM Tuner",
    _latest([("Main firmware", "V1.61"), ("Sub firmware", "V0.40"), ("REC firmware", "V0.17")]),
    _documents([
        ("Main Firmware V1.61 * This firmware is not for CD-400UDAB", "2024-12-23"),
        ("REC Firmware V0.17 * This firmware is not for CD-400UDAB", "2024-05-15"),
        ("Firmware (Main V1.54,Sub V0.40,REC V0.17) * This firmware is not for CD-400UDAB", "2024-05-15"),
    ]),
)

# One page, three units' latest-version tables: the console's comes first.
SONICVIEW = _support_page(
    "TASCAM Sonicview 16XP / TASCAM Sonicview 16dp | Digital Recording and Mixing Console",
    _latest([("Firmware", "V2.3.4"), ("Dante module firmware (Dante Brooklyn II)", "V1.0.4"), ("IF-MTR32 : Firmware", "V1.12")], heading=False),
    _latest([("Firmware", "V1.22"), ("Dante module firmware (Dante Brooklyn 3)", "V1.0.2")], heading=False),
    _documents([("Firmware update procedures", "2024-04-04"), ("Dante module firmware update procedures", "2023-11-14")]),
    _documents([("Firmware V2.3.4", "2026-08-27"), ("Firmware V2.3.3", "2026-06-03"), ("IF-MTR32 : Firmware V1.12", "2023-12-13")]),
)

# Current version stated, no download history.
US_4X4HR = _support_page(
    "US-4x4HR | 4-IN/4-OUT High-Resolution USB Audio/MIDI Interface",
    _latest([("Firmware", "V1.10"), ("Settings Panel V1.00 for Windows", "V1.00")]),
)

# Neither: a product whose support page states no firmware.
US_2X2HR = _support_page(
    "US-2x2HR | 2-IN/2-OUT High-Resolution USB Audio/MIDI Interface",
    _latest([("Settings Panel for Windows", "V1.00")]),
    _documents([("Owner's Manual", "2021-03-01")]),
)


def _parse(html):
    from src.scrapers.plugins.tascam import TascamScraper

    return TascamScraper()._parse_support_page(html)


def test_tascam_reads_dated_history_and_ignores_update_procedures():
    """"Firmware update procedures" is a PDF with a date of its own, not a release."""
    versions = _parse(MODEL_12)

    assert [(fw.version, fw.release_date.strftime("%Y-%m-%d")) for fw in versions] == [
        ("1.50", "2025-06-25"), ("1.42", "2024-06-05"),
    ]


def test_tascam_keeps_a_current_version_the_history_does_not_list():
    versions = _parse(US_4X4HR)

    assert [(fw.version, fw.release_date) for fw in versions] == [("1.10", None)]


def test_tascam_ignores_component_firmware():
    """CD-400U's Sub and REC firmware are components with their own numbering."""
    versions = [fw.version for fw in _parse(CD_400U)]

    assert versions == ["1.61"]


# SB-16D's page repeats the series' latest-version tables, the console's first, and
# carries its own download history.
SB_16D = _support_page(
    "SB-16D | 16-in/16-out Dante Stage Box",
    _latest([("Firmware", "V2.3.4"), ("Dante module firmware (Dante Brooklyn II)", "V1.0.4")], heading=False),
    _latest([("Firmware", "V1.22"), ("Dante module firmware (Dante Brooklyn 3)", "V1.0.2")], heading=False),
    _documents([("Firmware V1.22", "2026-06-03"), ("Firmware V1.21", "2025-04-02")]),
)


def test_tascam_ignores_a_component_listed_before_the_firmware():
    """Only a row labelled Firmware, System or Main firmware is the product's version."""
    page = _support_page(
        "MM-2D-E | 2-Channel Mic/Line Input/Output Dante Converter",
        _latest([("Dante Module Firmware", "V1.2.1.1"), ("Firmware", "V1.06")]),
    )

    assert [fw.version for fw in _parse(page)] == ["1.06"]


def test_tascam_reads_only_the_pages_own_unit_on_a_shared_page():
    """The Sonicview page carries its I/O rack's and an expansion card's firmware too."""
    versions = [fw.version for fw in _parse(SONICVIEW)]

    assert versions == ["2.3.4", "2.3.3"]
    assert "1.22" not in versions and "1.12" not in versions


def test_tascam_does_not_give_a_series_unit_the_consoles_version():
    """SB-16D's page opens with the Sonicview console's V2.3.4 table.

    Taking the first table gave SB-16D and IF-ST2110 the console's version as current.
    With several tables none is trusted, and the unit's own history speaks for it.
    """
    versions = [fw.version for fw in _parse(SB_16D)]

    assert versions == ["1.22", "1.21"]


HOME = """
<a href="https://tascam.com/us/category/audio_interface">Audio Interface</a>
<a href="https://tascam.com/us/category/multitrack_recorder">Multitrack Recorder</a>
<a href="https://tascam.com/us/product/model_12">Featured: Model 12</a>
"""


def _category(slugs, next_page=None):
    links = "".join(f'<a href="https://tascam.com/us/product/{slug}">{slug}</a>' for slug in slugs)
    pager = f'<a class="page-link pagination-num" href="?paged={next_page}">{next_page}</a>' if next_page else ""
    return f"<html><body>{links}{pager}</body></html>"


PAGES = {
    "https://tascam.com/us/": HOME,
    "https://tascam.com/us/category/audio_interface": _category(["us-4x4hr", "us-2x2hr"], next_page=2),
    "https://tascam.com/us/category/audio_interface?paged=2": _category(["sonicview_16xp"]),
    "https://tascam.com/us/category/multitrack_recorder": _category(["model_12", "cd-400u", "sonicview_16xp"]),
    "https://tascam.com/us/product/us-4x4hr/support": US_4X4HR,
    "https://tascam.com/us/product/us-2x2hr/support": US_2X2HR,
    "https://tascam.com/us/product/sonicview_16xp/support": SONICVIEW,
    "https://tascam.com/us/product/model_12/support": MODEL_12,
    "https://tascam.com/us/product/cd-400u/support": CD_400U,
}


def _scraper(pages=PAGES):
    from src.scrapers.plugins.tascam import TascamScraper

    scraper = TascamScraper()
    fetched = []

    async def _page(url, *_args, **_kwargs):
        fetched.append(url)
        return pages.get(url)

    scraper.fetch_page = _page
    return scraper, fetched


@pytest.mark.asyncio
async def test_tascam_lists_every_catalogue_product_that_states_firmware():
    """US-2x2HR states none, so a row for it would never report anything."""
    scraper, _ = _scraper()

    result = await scraper.fetch_device_list()

    assert result.success is True
    devices = {d.name: d for d in result.devices}
    assert set(devices) == {"US-4x4HR", "Sonicview 16XP / Sonicview 16dp", "Model 12", "CD-400U"}
    assert devices["Model 12"].firmware_page_url == "https://tascam.com/us/product/model_12/support"
    assert devices["Model 12"].product_url == "https://tascam.com/us/product/model_12"


@pytest.mark.asyncio
async def test_tascam_follows_the_category_pager():
    """Sonicview is on the second page of Audio Interface as well as on Multitrack."""
    scraper, fetched = _scraper()

    await scraper.fetch_device_list()

    assert "https://tascam.com/us/category/audio_interface?paged=2" in fetched


@pytest.mark.asyncio
async def test_tascam_files_products_by_the_categories_they_appear_in():
    scraper, _ = _scraper()

    categories = {d.name: d.category for d in (await scraper.fetch_device_list()).devices}

    # Listed under Audio Interface (on its second page) as well as Multitrack Recorder.
    assert categories["Sonicview 16XP / Sonicview 16dp"] == "audio_interface"
    assert categories["Model 12"] == "other"


@pytest.mark.asyncio
async def test_tascam_reads_each_page_once_per_scrape():
    scraper, fetched = _scraper()

    listing = await scraper.fetch_device_list()
    for device in listing.devices:
        await scraper.fetch_firmware_versions(device.name, device.firmware_page_url)

    assert sorted(fetched) == sorted(PAGES)


@pytest.mark.asyncio
async def test_tascam_fails_rather_than_dropping_products():
    missing_category = dict(PAGES)
    del missing_category["https://tascam.com/us/category/audio_interface?paged=2"]
    assert (await _scraper(missing_category)[0].fetch_device_list()).success is False

    missing_support = dict(PAGES)
    del missing_support["https://tascam.com/us/product/cd-400u/support"]
    assert (await _scraper(missing_support)[0].fetch_device_list()).success is False

    no_categories = {"https://tascam.com/us/": "<p>TASCAM</p>"}
    assert (await _scraper(no_categories)[0].fetch_device_list()).success is False


@pytest.mark.asyncio
async def test_tascam_reports_no_firmware_for_a_catalogued_product_without_any():
    scraper, _ = _scraper()

    result = await scraper.fetch_firmware_versions("US-2x2HR", "https://tascam.com/us/product/us-2x2hr/support")

    assert result.success is True
    assert result.firmware_versions == []
