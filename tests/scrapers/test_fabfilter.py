import pytest

from tests.support import _stub_fetch


def _ff_item(slug, name, line, installer=None):
    """One section of the download page, shaped like the live one."""
    files = ""
    if installer:
        files = (
            f'<a href="https://cdn-b.fabfilter.com/downloads/ff{installer}.dmg">Download for macOS</a>'
            f'<a href="https://cdn-b.fabfilter.com/downloads/ff{installer}x64.exe">Download for Windows (64-bit)</a>'
        )
    return (
        f'<div class="download-item offset-bottom" id="download-{slug}">'
        f"<h2>Download FabFilter {name}</h2><p>High-quality plug-in {line}</p>{files}</div>"
    )


FF_LEGACY = """
<h2>Additional Downloads</h2>
<h2>Legacy plug-ins</h2>
<h3>Pro-Q 3.29</h3><a href="https://cdn-b.fabfilter.com/downloads/ffproq329.dmg">macOS</a>
<h3>Pro-L 1.37</h3><a href="https://cdn-b.fabfilter.com/downloads/ffprol137.dmg">macOS</a>
<h2>Discontinued plug-in versions</h2>
<h3>Timeless 1.01</h3><a href="https://cdn-b.fabfilter.com/downloads/fftimeless101.dmg">macOS</a>
<h2>Legacy Total bundle installers</h2>
<h3>macOS 10.12</h3><a href="https://cdn-b.fabfilter.com/downloads/fftotalbundle_10.12.dmg">macOS</a>
<h3>macOS 10.6.8 (last RTAS versions)</h3>
<h2>Factory Presets</h2>
"""


def test_fabfilter_pairs_each_version_with_its_own_date():
    from src.scrapers.plugins.fabfilter import FabFilterScraper

    page = (_ff_item("pro-q-4-equalizer-plug-in", "Pro-Q 4", "4.13 — Jun 25, 2026", "proq413")
            + _ff_item("pro-c-3-compressor-plug-in", "Pro-C 3", "3.02 — Apr 16, 2026", "proc302"))
    parsed = FabFilterScraper()._parse_current(page)

    assert {n: (fw.version, fw.release_date.date().isoformat()) for n, fw in parsed.items()} == {
        "Pro-Q 4": ("4.13", "2026-06-25"),
        "Pro-C 3": ("3.02", "2026-04-16"),
    }


def test_fabfilter_skips_the_total_bundle():
    """The bundle packages the plug-ins; it is not a product with a version."""
    from src.scrapers.plugins.fabfilter import FabFilterScraper

    page = (_ff_item("fabfilter-total-bundle", "Total bundle", "")
            + _ff_item("pro-l-2-limiter-plug-in", "Pro-L 2", "2.26 — Apr 16, 2026", "prol226"))

    assert list(FabFilterScraper()._parse_current(page)) == ["Pro-L 2"]


def test_fabfilter_trusts_the_installer_over_stale_page_text():
    """A version the page states but the download does not match loses its date too."""
    from src.scrapers.plugins.fabfilter import FabFilterScraper

    page = _ff_item("pro-q-4-equalizer-plug-in", "Pro-Q 4", "4.12 — Jun 1, 2026", "proq413")
    firmware = FabFilterScraper()._parse_current(page)["Pro-Q 4"]

    assert firmware.version == "4.13"
    assert firmware.release_date is None


def test_fabfilter_splits_the_major_out_of_a_legacy_heading():
    """"Pro-Q 3.29" is Pro-Q 3 at 3.29; a major of 1 had no number in its name."""
    from src.scrapers.plugins.fabfilter import FabFilterScraper

    parsed = FabFilterScraper()._parse_legacy(FF_LEGACY)

    assert {n: fw.version for n, fw in parsed.items()} == {
        "Pro-Q 3": "3.29",
        "Pro-L": "1.37",
        "Timeless": "1.01",
    }


def test_fabfilter_does_not_read_os_versions_as_plugins():
    """"macOS 10.12" under the legacy bundle installers is not a product called macOS."""
    from src.scrapers.plugins.fabfilter import FabFilterScraper

    parsed = FabFilterScraper()._parse_legacy(FF_LEGACY)

    assert not any(name.startswith("macOS") for name in parsed)


@pytest.mark.asyncio
async def test_fabfilter_lists_current_and_legacy_plugins_from_two_fetches():
    from src.scrapers.plugins.fabfilter import FabFilterScraper as FF

    scraper = FF()
    asked = _stub_fetch(scraper, {
        FF.DOWNLOAD_URL: _ff_item("pro-q-4-equalizer-plug-in", "Pro-Q 4", "4.13 — Jun 25, 2026", "proq413"),
        FF.LEGACY_URL: FF_LEGACY,
    })

    devices = (await scraper.fetch_device_list()).devices
    for device in devices:
        await scraper.fetch_firmware_versions(device.name, device.firmware_page_url)

    assert len(asked) == 2
    assert {d.name: d.firmware_page_url for d in devices} == {
        "Pro-Q 4": FF.DOWNLOAD_URL,
        "Pro-Q 3": FF.LEGACY_URL,
        "Pro-L": FF.LEGACY_URL,
        "Timeless": FF.LEGACY_URL,
    }
    assert {d.category for d in devices} == {"vst_plugin"}


@pytest.mark.asyncio
async def test_fabfilter_still_reports_current_plugins_without_the_legacy_page():
    from src.scrapers.plugins.fabfilter import FabFilterScraper as FF

    scraper = FF()
    _stub_fetch(scraper, {
        FF.DOWNLOAD_URL: _ff_item("pro-q-4-equalizer-plug-in", "Pro-Q 4", "4.13 — Jun 25, 2026", "proq413"),
    })

    listing = await scraper.fetch_device_list()

    assert listing.success is True
    assert [d.name for d in listing.devices] == ["Pro-Q 4"]


@pytest.mark.asyncio
async def test_fabfilter_fails_loudly_when_the_download_page_has_no_versions():
    from src.scrapers.plugins.fabfilter import FabFilterScraper as FF

    scraper = FF()
    _stub_fetch(scraper, {FF.DOWNLOAD_URL: "<p>Site maintenance</p>", FF.LEGACY_URL: FF_LEGACY})

    assert (await scraper.fetch_device_list()).success is False
