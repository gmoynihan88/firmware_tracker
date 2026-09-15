import pytest

from tests.support import _stub_fetch


def _zoom_page(*entries) -> str:
    """(link text, href) pairs, the shape Zoom's firmware page uses."""
    return "".join(
        f'<div class="row"><a href="{href}">{text}</a></div>' for text, href in entries
    )


def test_zoom_reads_both_wordings():
    """"H2n Firmware" and "R20 System Version 3.30" are both firmware links.

    The first filter required the word "Firmware" and silently dropped three
    products whose link says "System Version" instead.
    """
    from src.scrapers.plugins.zoom import ZoomScraper

    parsed = ZoomScraper()._parse(_zoom_page(
        ("H2n Firmware", "/documents/1/H2n_v3.00E.zip"),
        ("R20 System Version 3.30", "/documents/2/R20_v3.40_E.zip"),
    ))

    assert {name: fw.version for name, fw in parsed.items()} == {
        "H2n": "3.00",
        "R20": "3.40",
    }


def test_zoom_trusts_the_filename_over_a_stale_title():
    """F6's link says 2.00 and points at F6_v2.20E.zip; 2.20 is what ships."""
    from src.scrapers.plugins.zoom import ZoomScraper

    parsed = ZoomScraper()._parse(_zoom_page(
        ("F6 Firmware 2.00 + Audio Driver", "/documents/3/F6_v2.20E.zip"),
    ))

    assert parsed["F6"].version == "2.20"


def test_zoom_falls_back_to_the_title_when_the_filename_has_no_version():
    from src.scrapers.plugins.zoom import ZoomScraper

    parsed = ZoomScraper()._parse(_zoom_page(
        ("L-12 System Version 2.14", "/documents/4/L12_firmware.zip"),
    ))

    assert parsed["L-12"].version == "2.14"


def test_zoom_strips_the_language_marker_but_keeps_a_revision_letter():
    """Uppercase E is the English build; a lowercase letter is a real release."""
    from src.scrapers.plugins.zoom import ZoomScraper

    parsed = ZoomScraper()._parse(_zoom_page(
        ("H2n Firmware", "/documents/1/H2n_v3.00E.zip"),
        ("H6 Firmware", "/documents/5/H6_v2.50a_E.zip"),
    ))

    assert parsed["H2n"].version == "3.00"
    assert parsed["H6"].version == "2.50a"


def test_zoom_ignores_accessibility_files():
    """"Guide Sound Version 1.00" matches the wording and is not firmware."""
    from src.scrapers.plugins.zoom import ZoomScraper

    parsed = ZoomScraper()._parse(_zoom_page(
        ("H1essential Accessibility File Guide Sound Version 1.00",
         "/documents/6/H1e_guide_v1.00.zip"),
    ))

    assert parsed == {}


def test_zoom_collapses_the_windows_and_mac_builds_of_one_product():
    """MS-90LP+, AC-2 and B1X Four each publish two updaters, one firmware."""
    from src.scrapers.plugins.zoom import ZoomScraper

    parsed = ZoomScraper()._parse(_zoom_page(
        ("MS-90LP+ Firmware (Windows)", "/documents/7/MS90LPplus_v1.10E_win.zip"),
        ("MS-90LP+ Firmware (Mac)", "/documents/8/MS90LPplus_v1.10E_mac.zip"),
    ))

    assert list(parsed) == ["MS-90LP+"]
    assert parsed["MS-90LP+"].version == "1.10"


def test_zoom_keeps_the_higher_version_when_a_product_appears_twice():
    from src.scrapers.plugins.zoom import ZoomScraper

    parsed = ZoomScraper()._parse(_zoom_page(
        ("H8 Firmware", "/documents/9/H8_v2.10E.zip"),
        ("H8 Firmware", "/documents/10/H8_v2.20E.zip"),
    ))

    assert parsed["H8"].version == "2.20"
    # and the same page in the other order
    reversed_page = ZoomScraper()._parse(_zoom_page(
        ("H8 Firmware", "/documents/10/H8_v2.20E.zip"),
        ("H8 Firmware", "/documents/9/H8_v2.10E.zip"),
    ))
    assert reversed_page["H8"].version == "2.20"


def test_zoom_drops_parenthesised_file_sizes():
    """"Firmware ReadMe (76.74 kB)" must not read 76.74 as a version."""
    from src.scrapers.plugins.zoom import ZoomScraper

    parsed = ZoomScraper()._parse(_zoom_page(
        ("H6 Firmware ReadMe (76.74 kB)", "/documents/11/H6_readme.pdf"),
    ))

    assert parsed == {}


def test_zoom_stores_no_dates():
    """Zoom publishes none, so none are invented from the day of the scrape."""
    from src.scrapers.plugins.zoom import ZoomScraper

    parsed = ZoomScraper()._parse(_zoom_page(
        ("H2n Firmware", "/documents/1/H2n_v3.00E.zip"),
    ))

    assert parsed["H2n"].release_date is None


@pytest.mark.asyncio
async def test_zoom_reads_the_page_once_for_the_whole_catalogue():
    from src.scrapers.plugins.zoom import ZoomScraper

    scraper = ZoomScraper()
    asked = _stub_fetch(scraper, {ZoomScraper.FIRMWARE_URL: _zoom_page(
        ("UAC-8 Firmware", "/documents/12/UAC8_v1.21E.zip"),
        ("G11 Firmware", "/documents/13/G11_v2.10E.zip"),
        ("H5 Firmware", "/documents/14/H5_v2.10E.zip"),
    )})

    devices = await scraper.fetch_device_list()
    for device in devices.devices:
        await scraper.fetch_firmware_versions(device.name, device.firmware_page_url)

    assert len(asked) == 1
    assert [(d.name, d.category) for d in devices.devices] == [
        ("G11", "guitar_pedal"),
        ("H5", "other"),
        ("UAC-8", "audio_interface"),
    ]


@pytest.mark.asyncio
async def test_zoom_fails_loudly_when_the_page_yields_nothing():
    """An empty read is a broken page here -- Zoom always lists something."""
    from src.scrapers.plugins.zoom import ZoomScraper

    scraper = ZoomScraper()
    _stub_fetch(scraper, {ZoomScraper.FIRMWARE_URL: "<p>Maintenance</p>"})

    assert (await scraper.fetch_device_list()).success is False
