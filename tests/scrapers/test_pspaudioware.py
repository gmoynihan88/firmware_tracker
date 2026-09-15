import pytest

from tests.support import _stub_fetch


def _psp_product(name, *hrefs) -> str:
    """A product page: an h1, the macOS minimum, and the trial links."""
    links = "".join(f'<a href="{h}">30-day trial</a>' for h in hrefs)
    return (f"<h1>{name}</h1>"
            "<p>Requires macOS 10.14 or later. Tested on 10.14.</p>"
            f"{links}")


PSP_EU = ("https://download-eu2.pspaudioware.net/PSP_VintageWarmer2/OSX/native/"
          "PSP_VintageWarmer2_2.11.0_macOS.dmg")


PSP_S3 = ("https://s3.us-west-1.amazonaws.com/download-us1.pspaudioware.net/release/"
          "PSP_Echo/OSX/PSP_Echo_1.5.3_macOS.dmg")


def test_psp_reads_the_version_from_the_installer_filename():
    from src.scrapers.plugins.pspaudioware import PSPaudiowareScraper

    name, version = PSPaudiowareScraper()._parse_product(
        _psp_product("PSP VintageWarmer2", PSP_EU))

    assert (name, version) == ("PSP VintageWarmer2", "2.11.0")


def test_psp_reads_both_download_hosts():
    """A dozen products are served from S3 and were invisible to a host match."""
    from src.scrapers.plugins.pspaudioware import PSPaudiowareScraper

    _, from_s3 = PSPaudiowareScraper()._parse_product(
        _psp_product("PSP Echo", PSP_S3))

    assert from_s3 == "1.5.3"


def test_psp_ignores_the_macos_requirement_on_the_page():
    """10.14 is the minimum macOS and appears twice; only hrefs are read."""
    from src.scrapers.plugins.pspaudioware import PSPaudiowareScraper

    name, version = PSPaudiowareScraper()._parse_product(
        _psp_product("PSP ClassicQ"))

    assert (name, version) == ("PSP ClassicQ", None)


def test_psp_does_not_read_the_edition_out_of_the_product_name():
    """"PSP auralComp v. 2" is an edition; the installer says 2.0.2."""
    from src.scrapers.plugins.pspaudioware import PSPaudiowareScraper

    href = ("https://download-eu2.pspaudioware.net/PSP_auralComp/OSX/native/"
            "PSP_auralComp_2.0.2_macOS.dmg")
    name, version = PSPaudiowareScraper()._parse_product(
        _psp_product("PSP auralComp v. 2", href))

    assert (name, version) == ("PSP auralComp v. 2", "2.0.2")


def test_psp_collapses_the_windows_and_mac_installers():
    from src.scrapers.plugins.pspaudioware import PSPaudiowareScraper

    win = PSP_EU.replace("OSX", "Windows").replace("_macOS.dmg", "_Win.exe")
    _, version = PSPaudiowareScraper()._parse_product(
        _psp_product("PSP VintageWarmer2", PSP_EU, win))

    assert version == "2.11.0"


@pytest.mark.asyncio
async def test_psp_flags_products_with_no_installer_rather_than_dropping_them():
    """Bundles and the older plug-ins publish no trial, so they say why."""
    from src.scrapers.plugins.pspaudioware import PSPaudiowareScraper as PSP

    scraper = PSP()
    _stub_fetch(scraper, {
        PSP.PRODUCTS_URL: ('<a href="/products/psp-vintagewarmer2">a</a>'
                           '<a href="/products/psp-mixpack2">b</a>'),
        "https://www.pspaudioware.com/products/psp-vintagewarmer2":
            _psp_product("PSP VintageWarmer2", PSP_EU),
        "https://www.pspaudioware.com/products/psp-mixpack2":
            _psp_product("PSP MixPack2"),
    })

    devices = (await scraper.fetch_device_list()).devices
    flags = {d.name: d.firmware_availability for d in devices}

    assert flags == {"PSP VintageWarmer2": None, "PSP MixPack2": "not_published"}

    # and the flagged one succeeds while reporting nothing, rather than failing
    empty = await scraper.fetch_firmware_versions(
        "PSP MixPack2", "https://www.pspaudioware.com/products/psp-mixpack2")
    assert empty.success is True and empty.firmware_versions == []


@pytest.mark.asyncio
async def test_psp_fetches_each_product_page_once():
    from src.scrapers.plugins.pspaudioware import PSPaudiowareScraper as PSP

    scraper = PSP()
    asked = _stub_fetch(scraper, {
        PSP.PRODUCTS_URL: '<a href="/products/psp-echo">a</a>',
        "https://www.pspaudioware.com/products/psp-echo":
            _psp_product("PSP Echo", PSP_S3),
    })

    devices = await scraper.fetch_device_list()
    for device in devices.devices:
        await scraper.fetch_firmware_versions(device.name, device.firmware_page_url)

    assert len(asked) == 2          # the index, then the one product


@pytest.mark.asyncio
async def test_psp_fails_loudly_when_the_index_lists_nothing():
    from src.scrapers.plugins.pspaudioware import PSPaudiowareScraper as PSP

    scraper = PSP()
    _stub_fetch(scraper, {PSP.PRODUCTS_URL: "<p>You need to be logged in</p>"})

    assert (await scraper.fetch_device_list()).success is False
