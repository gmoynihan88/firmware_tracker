import pytest


def _box(label, href):
    return (
        '<div class="icon-box icon-box-bottom"><div class="icon-box-content">'
        f'<div class="icon-box-heading icon-box-fa-1x"><h3 class="h3">{label}</h3></div></div>'
        f'<div class="icon-box-icon fa-container"><a class="text-default-color custom-link" href="{href}" role="button" target="_blank">'
        '<i class="fa fa-download fa-1x fa-fw"></i></a></div></div>'
    )


def _row(name, boxes):
    return (
        '<div class="wpb_row row-inner">'
        '<div class="wpb_column pos-top pos-center align_left column_child col-lg-3 single-internal-gutter">'
        f'<div class="uncol style-dark"><div class="vc_custom_heading_wrap"><div class="heading-text el-text"><h3 class="h3"><span>{name}</span></h3></div></div></div></div>'
        f'<div class="wpb_column pos-top pos-center align_center column_child col-lg-3 no-internal-gutter">{"".join(boxes)}</div>'
        '</div>'
    )


UPLOADS = "https://dreadbox-fx.com/wp-content/uploads"

# As served: an outer row whose first heading is "Abyss" wraps every product row.
SUPPORT = (
    '<div class="wpb_row row-inner"><div class="wpb_column column_child">'
    '<h3 class="h3"><span>Abyss</span></h3></div><div class="wpb_column">'
    + _row("Abyss", [_box("User Manual", f"{UPLOADS}/2024/01/Abyss-Manual.pdf")])
    + _row("Artemis", [
        _box("Factory Presets 1.1.0", f"{UPLOADS}/2025/08/Factory-Presets-v1.1.0.zip"),
        _box("Firmware Update 1.2.0", f"{UPLOADS}/2026/05/Artemis_1.2.0.zip"),
        _box("Firmware Update 1.1.0", f"{UPLOADS}/2025/08/Artemis_1.1.0.zip"),
        _box("Factory Firmware", f"{UPLOADS}/2025/05/Artemis-Factory-FirmwarePresets.zip"),
    ])
    + _row("Erebus v3", [_box("Firmware", f"{UPLOADS}/2025/04/ErebusV3_Firmware-_V1_01.zip"),
                         _box("User Manual", f"{UPLOADS}/2025/04/ErebusV3_Manual.pdf")])
    + _row("Nymphes", [_box("Firmware", f"{UPLOADS}/2025/04/Nymphes-Firmware-Update-V2.1.zip")])
    + _row("Typhon", [
        _box("Typhon Updater 4.2.1 MacOS", f"{UPLOADS}/2026/07/Typhon-Updater-4.2.1-macOS.zip"),
        _box("Typhon Updater 4.2.1 Windows", f"{UPLOADS}/2026/07/Typhon-Updater-4.2.1-windows.zip"),
        _box("Typhon Preset Manager 4.2 MacOS", f"{UPLOADS}/2026/04/Typhon-Preset-Manager-4.2.0-Macos.zip"),
    ])
    + "</div></div>"
)


def _sitemap(urls):
    rows = "".join(f'<tr><td><a href="{u}">{u}</a></td><td>2026-07-06 13:15 +00:00</td></tr>' for u in urls)
    return f'<html><head><title>XML Sitemap</title></head><body><table id="sitemap"><tbody>{rows}</tbody></table></body></html>'


def _post(title, published):
    return (
        f'<html><head><meta content="{published}" property="article:published_time"/></head>'
        f'<body><h1 class="fontsize-338686 font-weight-700"><span>{title}</span></h1></body></html>'
    )


PAGES = {
    "https://dreadbox-fx.com/support/": SUPPORT,
    "https://dreadbox-fx.com/post-sitemap.xml": _sitemap([
        "https://dreadbox-fx.com/artemis-update-v1-2-0/",
        "https://dreadbox-fx.com/typhon-update-v4-2-1/",
        "https://dreadbox-fx.com/nymphes-v2-firmware-update/",
        "https://dreadbox-fx.com/effects-drums-with-harris-manthos/",
    ]),
    "https://dreadbox-fx.com/artemis-update-v1-2-0/": _post("Artemis Update v1.2.0", "2026-05-28T11:27:12+00:00"),
    "https://dreadbox-fx.com/typhon-update-v4-2-1/": _post("Typhon Update v4.2.1", "2026-07-06T13:15:46+00:00"),
    # Names V2, not the V2.1 offered: dates nothing.
    "https://dreadbox-fx.com/nymphes-v2-firmware-update/": _post("NYMPHES  V2 Firmware Update", "2022-02-16T12:30:13+00:00"),
}


def _scraper(pages=PAGES):
    from src.scrapers.plugins.dreadbox import DreadboxScraper

    scraper = DreadboxScraper()
    fetched = []

    async def _page(url, *_args, **_kwargs):
        fetched.append(url)
        return pages.get(url)

    scraper.fetch_page_js = _page
    return scraper, fetched


def test_dreadbox_files_each_download_under_its_nearest_row():
    """An outer row headed "Abyss" wraps them all; the outermost row gets everything wrong."""
    from src.scrapers.plugins.dreadbox import DreadboxScraper

    products = DreadboxScraper()._parse_support(SUPPORT)

    assert products == {
        "Artemis": ["1.2.0", "1.1.0"],
        "Erebus v3": ["1.01"],
        "Nymphes": ["2.1"],
        "Typhon": ["4.2.1"],
    }


def test_dreadbox_reads_the_version_from_the_file_when_the_label_has_none():
    """"ErebusV3_Firmware-_V1_01.zip" is 1.01; the V3 is the model."""
    from src.scrapers.plugins.dreadbox import DreadboxScraper

    scraper = DreadboxScraper()

    assert scraper._version("Firmware", f"{UPLOADS}/2025/04/ErebusV3_Firmware-_V1_01.zip") == "1.01"
    assert scraper._version("Firmware Update 1.2.0", f"{UPLOADS}/2026/05/whatever.zip") == "1.2.0"
    assert scraper._version("Factory Firmware", f"{UPLOADS}/2025/05/Artemis-Factory-FirmwarePresets.zip") is None


@pytest.mark.asyncio
async def test_dreadbox_dates_a_release_only_from_a_post_naming_its_version():
    scraper, _ = _scraper()

    listing = await scraper.fetch_device_list()
    assert [d.name for d in listing.devices] == ["Artemis", "Erebus v3", "Nymphes", "Typhon"]

    artemis = (await scraper.fetch_firmware_versions("Artemis", scraper.SUPPORT_URL)).firmware_versions
    assert [(fw.version, fw.release_date.strftime("%Y-%m-%d") if fw.release_date else None) for fw in artemis] == [
        ("1.2.0", "2026-05-28"), ("1.1.0", None),
    ]
    typhon = (await scraper.fetch_firmware_versions("Typhon", scraper.SUPPORT_URL)).firmware_versions
    assert typhon[0].release_date.strftime("%Y-%m-%d") == "2026-07-06"
    # "NYMPHES V2 Firmware Update" is not a post about V2.1, and the upload month is
    # not a release date.
    nymphes = (await scraper.fetch_firmware_versions("Nymphes", scraper.SUPPORT_URL)).firmware_versions
    assert nymphes[0].release_date is None


@pytest.mark.asyncio
async def test_dreadbox_reads_only_update_posts_and_each_page_once():
    scraper, fetched = _scraper()

    listing = await scraper.fetch_device_list()
    for device in listing.devices:
        await scraper.fetch_firmware_versions(device.name, device.firmware_page_url)

    assert sorted(fetched) == sorted(PAGES)
    assert "https://dreadbox-fx.com/effects-drums-with-harris-manthos/" not in fetched


@pytest.mark.asyncio
async def test_dreadbox_fails_loudly():
    no_support = dict(PAGES)
    del no_support["https://dreadbox-fx.com/support/"]
    assert (await _scraper(no_support)[0].fetch_device_list()).success is False

    no_sitemap = dict(PAGES)
    del no_sitemap["https://dreadbox-fx.com/post-sitemap.xml"]
    assert (await _scraper(no_sitemap)[0].fetch_device_list()).success is False

    missing_post = dict(PAGES)
    del missing_post["https://dreadbox-fx.com/typhon-update-v4-2-1/"]
    assert (await _scraper(missing_post)[0].fetch_device_list()).success is False

    scraper, _ = _scraper()
    assert (await scraper.fetch_firmware_versions("Abyss", "")).success is False
