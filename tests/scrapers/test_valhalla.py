import pytest

from tests.support import _stub_fetch


def _vh_form(slug, name, label, filename, platform="Mac Demo"):
    """One download form on the demos page, with the hidden inputs the live one has."""
    return (
        '<li><form action="#" class="demo-download-form" method="post">'
        f'<input type="hidden" name="plugin_slug" value="{slug}"/>'
        f'<input type="hidden" name="plugin_name" value="{name}"/>'
        f'<input type="hidden" name="demo_name" value="{label}"/>'
        f'<input type="hidden" name="download_url" value="https://valhallaproduction.s3.us-west-2.amazonaws.com/{slug}/demo/{filename}"/>'
        f'<input type="hidden" name="platform" value="{platform}"/>'
        f'<button type="submit">{label}</button></form></li>'
    )


def test_valhalla_reads_every_way_the_label_is_written():
    from src.scrapers.plugins.valhalla import ValhallaDSPScraper

    page = (
        _vh_form("futureverb", "Valhalla FutureVerb Demo", "Version 1.0.2: Updated 11/22/2025", "ValhallaFutureVerbOSXDemo_1_0_2.dmg")
        + _vh_form("shimmer", "Valhalla Shimmer Demo", "Version 1.3.0 Updated 1/30/2023", "ValhallaShimmerOSXDemo_1_3_0.dmg")
        + _vh_form("plate", "Valhalla Plate Demo", "Version 1.6.3: Updated 10/07/20", "ValhallaPlateDemoWin_1_6_3b3.zip", "Windows Demo")
        + _vh_form("freqecho", "Valhalla Freq Echo", "Latest: Version 1.2.8", "ValhallaFreqEchoOSX_1_2_8.dmg")
    )
    parsed = ValhallaDSPScraper()._parse(page)

    got = {n: (fw.version, fw.release_date.date().isoformat() if fw.release_date else None)
           for n, fw in parsed.items()}
    assert got == {
        "Valhalla FutureVerb": ("1.0.2", "2025-11-22"),
        "Valhalla Shimmer": ("1.3.0", "2023-01-30"),          # no colon
        "Valhalla Plate": ("1.6.3", "2020-10-07"),            # two-digit year
        "Valhalla Freq Echo": ("1.2.8", None),                # free: no date at all
    }


def test_valhalla_records_the_newest_build_when_windows_lags():
    """Shimmer ships 1.3.0 for Mac and 1.2.2 for Windows; the date goes with 1.3.0."""
    from src.scrapers.plugins.valhalla import ValhallaDSPScraper

    page = (
        _vh_form("shimmer", "Valhalla Shimmer Demo", "Version 1.2.2: Updated 10/07/20", "ValhallaShimmerDemoWin_V1_2_2v2.zip", "Windows Demo")
        + _vh_form("shimmer", "Valhalla Shimmer Demo", "Version 1.3.0 Updated 1/30/2023", "ValhallaShimmerOSXDemo_1_3_0.dmg")
    )
    firmware = ValhallaDSPScraper()._parse(page)["Valhalla Shimmer"]

    assert firmware.version == "1.3.0"
    assert firmware.release_date.date().isoformat() == "2023-01-30"


def test_valhalla_trusts_the_installer_over_a_stale_label():
    from src.scrapers.plugins.valhalla import ValhallaDSPScraper

    page = _vh_form("room", "Valhalla Room Demo", "Version 2.0.4: Updated 3/15/2024", "ValhallaRoomDemoWin_V2_0_5.zip", "Windows Demo")
    firmware = ValhallaDSPScraper()._parse(page)["Valhalla Room"]

    assert firmware.version == "2.0.5"
    assert firmware.release_date is None


def test_valhalla_does_not_read_build_suffixes_into_the_version():
    """`_V1_2_2v2.zip` is 1.2.2 and `_1_6_3b3.zip` is 1.6.3."""
    from src.scrapers.plugins.valhalla import ValhallaDSPScraper

    # Labels without a version, so the filename is the only source: a pattern that
    # stopped matching suffixed names would lose these products, not quietly fall
    # back to a label that happens to agree.
    page = (
        _vh_form("shimmer", "Valhalla Shimmer Demo", "Download", "ValhallaShimmerDemoWin_V1_2_2v2.zip")
        + _vh_form("plate", "Valhalla Plate Demo", "Download", "ValhallaPlateDemoWin_1_6_3b3.zip")
    )
    parsed = ValhallaDSPScraper()._parse(page)

    assert parsed["Valhalla Shimmer"].version == "1.2.2"
    assert parsed["Valhalla Plate"].version == "1.6.3"


def test_valhalla_names_drop_demo_and_use_the_product_page_spelling():
    from src.scrapers.plugins.valhalla import ValhallaDSPScraper

    page = (
        _vh_form("ubermod", "Valhalla Ubermod Demo", "Version 1.2.8: Updated 1/30/2023", "ValhallaUberModOSXDemo_1_2_8.dmg")
        + _vh_form("supermassive", "Valhalla Supermassive", "Latest: Version 5.0.0: Updated 11/26/2025", "ValhallaSupermassiveOSX_5_0_0.dmg")
    )

    assert sorted(ValhallaDSPScraper()._parse(page)) == ["Valhalla Supermassive", "Valhalla UberMod"]


@pytest.mark.asyncio
async def test_valhalla_reads_the_page_once_for_the_whole_range():
    from src.scrapers.plugins.valhalla import ValhallaDSPScraper as VH

    scraper = VH()
    asked = _stub_fetch(scraper, {VH.DOWNLOADS_URL: (
        _vh_form("delay", "Valhalla Delay Demo", "Version 3.0.5: Updated 5/20/2025", "ValhallaDelayOSXDemo_3_0_5.dmg")
        + _vh_form("room", "Valhalla Room Demo", "Version 2.0.5: Updated 3/15/2024", "ValhallaRoomOSXDemo_2_0_5.dmg")
    )})

    devices = (await scraper.fetch_device_list()).devices
    for device in devices:
        await scraper.fetch_firmware_versions(device.name, device.firmware_page_url)

    assert len(asked) == 1
    assert [d.name for d in devices] == ["Valhalla Delay", "Valhalla Room"]
    assert {d.category for d in devices} == {"vst_plugin"}


@pytest.mark.asyncio
async def test_valhalla_fails_loudly_when_the_page_has_no_downloads():
    from src.scrapers.plugins.valhalla import ValhallaDSPScraper as VH

    scraper = VH()
    _stub_fetch(scraper, {VH.DOWNLOADS_URL: "<p>Download in Progress...</p>"})

    assert (await scraper.fetch_device_list()).success is False
