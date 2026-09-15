import pytest

from tests.support import _stub_fetch


def _rme_item(title, date, filename, description, products, driver="flash"):
    """One download item as RME's downloads page writes it."""
    return (
        f'<li data-driver="{driver}" data-product="1">'
        f'<div class="sub-row-title"><div>{title}</div><div>{date}</div>'
        f'<div><a href="https://rme-audio.de/downloads/{filename}">{filename}</a></div></div>'
        f'<div class="sub-row-description"><div><p>{description}</p></div></div>'
        f'<div class="sub-row-products"><div class="supported-products"><b>Supported products</b><br/>{products}</div></div>'
        "</li>"
    )


def _rme_page(*items):
    return '<html><body><ul class="dl-v2-downloads">' + "".join(items) + "</ul></body></html>"


RME_PAGE = _rme_page(
    _rme_item("M-1620 Pro D Firmware Update", "2026-09-07", "M-1620_Pro_D_1_3_3.zip",
              "<strong>Firmware 1.3.3</strong>. Main update.", "M-1620 Pro D"),
    _rme_item("Firmware update for M-32 DA Pro II", "2025-10-14", "M-32_DA_Pro_II_3_0_8.zip",
              "includes firmware version 3.0.8. Main update.", "M-32 AD / M-32 DA Pro II"),
    _rme_item("Firmware update for M-32 AD Pro II", "2025-04-02", "M-32_AD_Pro_II_3_0_7.zip",
              "includes firmware version 3.0.7. Adds MILAN certification.", "M-32 AD / M-32 DA Pro II"),
    _rme_item("macOS HDSPe AoX Driver &amp; Firmware Package", "2026-08-17", "AoX_MAC.zip",
              "includes Driver 1.01 with Settings 1.30 and Firmware version 1.5.0-67 for macOS 12.3 and up",
              "HDSPe AoX-D, HDSPe AoX-M"),
    _rme_item("Windows HDSPe AoX Driver &amp; Firmware Package", "2026-08-18", "AoX_WIN.zip",
              "includes Driver 1.2.4 and Firmware version 1.5.0-67.", "HDSPe AoX-D, HDSPe AoX-M"),
    _rme_item("Mac OS Flash Update Tool for Fireface UFX, 802, UCX, UCX II, UC, Babyface/Pro", "2025-09-01",
              "fut_usb_mac.zip", "Update to version UFX: 361/163/344/29, Babyface Pro &amp; FS: 211/322.",
              "Babyface Pro FS, Fireface UFX"),
    _rme_item("Mac OS X Intel Flash Update Tool for Fireface UFX+ (USB+Thunderbolt)", "2025-08-06",
              "fut_usb_tb_mac.zip", "Update to firmware version USB 55, TB 112, DSP 62 (AKM).", "Fireface UFX+"),
    _rme_item("Firmware update Digiface Ravenna - RAV2 module", "2026-09-01", "rav2.zip",
              "Firnware update for RAV2 module, update to hw 038 sw 1.31 .", "Digiface Ravenna"),
    _rme_item("12Mic Firmware Update 2.x", "2025-03-31", "12Mic_2_0_1.zip",
              "Firmware 2.0.1 . Main update.", "12Mic"),
    _rme_item("12Mic Firmware Update", "2023-11-06", "12mic-1.7.1.zip",
              "Firmware 1.7.1 , 06/11/2023. Main update.", "12Mic"),
    _rme_item("Flash Update Tool for Fireface 400 (Windows, Archive)", "2010-11-27", "fut_win_fire_400.zip",
              "Update to firmware revision[nbsp] 1.71 .", "Fireface 400"),
    _rme_item("Mac OS X Flash Update Tool for Fireface 400", "2009-07-09", "fut_mac_fire_400.gz",
              "PPC and Intel Macs (Universal Binary). Update to firmware revision 1.69 .", "Fireface 400"),
    # One title, two products: only 1.71 follows "firmware", so it looks like one version.
    _rme_item("Mac OS X Intel Flash Update Tool for Fireface 400 and Fireface 800", "2012-05-22",
              "fut_mac_fire_x86.zip", "Update to firmware revision 1.71 and 2.77 .", "Fireface 400, Fireface 800"),
    _rme_item("Mac OS X Intel Flash Update Tool ARC USB", "2018-10-30", "fut_arcusb_mac_v7.zip",
              "Update to version 7. Adds support for SysEx communication.", "ARC USB"),
    _rme_item("Mac OS X Intel driver for Fireface 400, 800, UCX, UFX", "2012-01-19", "driver.zip",
              "Version 3.06. This driver requires firmware 1.70 or higher.", "Fireface 400", driver="driver"),
)


def test_rme_reads_one_version_per_single_product_firmware_item():
    from src.scrapers.plugins.rme import RMEScraper

    products = RMEScraper()._parse_downloads(RME_PAGE)
    expected = {
        "M-1620 Pro D": "1.3.3",
        "M-32 DA Pro II": "3.0.8",
        "M-32 AD Pro II": "3.0.7",
        "HDSPe AoX": "1.5.0-67",
        "12Mic": "2.0.1",
        "Fireface 400": "1.71",
        "ARC USB": "7",
    }

    assert {name: products[name][0].version for name in expected} == expected


def test_rme_names_products_from_the_title_not_the_shared_products_label():
    """The AD and DA converters list one "M-32 AD / M-32 DA Pro II" label with different firmware."""
    from src.scrapers.plugins.rme import RMEScraper

    products = RMEScraper()._parse_downloads(RME_PAGE)

    assert products["M-32 DA Pro II"][0].version == "3.0.8"
    assert products["M-32 AD Pro II"][0].version == "3.0.7"
    assert "M-32 AD / M-32 DA Pro II" not in products


def test_rme_skips_what_names_no_comparable_firmware():
    """The RAV2 module's "hw 038 sw 1.31" prose, and a single version under a two-product title."""
    from src.scrapers.plugins.rme import RMEScraper

    products = RMEScraper()._parse_downloads(RME_PAGE)

    for name in ("Digiface Ravenna - RAV2 module", "Digiface Ravenna", "Fireface 400 and Fireface 800", "Fireface UFX+"):
        assert name not in products


def test_rme_reads_only_firmware_from_a_driver_and_firmware_package():
    """Driver 1.01 and Settings 1.30 are not the card's firmware; Mac and Windows are one release."""
    from src.scrapers.plugins.rme import RMEScraper

    aox = RMEScraper()._parse_downloads(RME_PAGE)["HDSPe AoX"]

    assert [(fw.version, fw.release_date.date().isoformat()) for fw in aox] == [("1.5.0-67", "2026-08-17")]


def test_rme_keeps_each_products_history_and_ignores_driver_items():
    """A driver's "requires firmware 1.70" is not a Fireface 400 release, and "[nbsp]" is a space."""
    from src.scrapers.plugins.rme import RMEScraper

    products = RMEScraper()._parse_downloads(RME_PAGE)

    assert [fw.version for fw in products["12Mic"]] == ["2.0.1", "1.7.1"]
    assert [fw.version for fw in products["Fireface 400"]] == ["1.71", "1.69"]
    assert products["Fireface 400"][0].download_url.endswith("fut_win_fire_400.zip")


def test_rme_prefers_the_firmware_statement_over_other_versions_named():
    """The M-Series tool also names "MIDI Remote ... version 1.6"; the AoX package, Driver and Settings."""
    from src.scrapers.plugins.rme import RMEScraper

    scraper = RMEScraper()

    assert scraper._firmware_version(
        "Includes firmware version 2.1. New: ADAT Copy mode. Supported by MIDI Remote Win/Mac version 1.6 and higher."
    ) == "2.1"
    assert scraper._firmware_version(
        "includes Driver 1.01 with Settings 1.30 and Firmware version 1.5.0-67 for macOS 12.3 and up"
    ) == "1.5.0-67"
    assert scraper._firmware_version("Update to version 7. Adds support for SysEx communication.") == "7"
    # Two firmware versions for two products is not one version.
    assert scraper._firmware_version("Update to firmware revision 1.71 and firmware revision 2.77 .") is None


@pytest.mark.asyncio
async def test_rme_lists_devices_from_one_fetch():
    from src.scrapers.plugins.rme import RMEScraper

    scraper = RMEScraper()
    asked = _stub_fetch(scraper, {RMEScraper.DOWNLOADS_URL: RME_PAGE})

    devices = {d.name: d.category for d in (await scraper.fetch_device_list()).devices}

    assert asked == [RMEScraper.DOWNLOADS_URL]
    assert devices["ARC USB"] == "midi_controller"
    assert devices["M-1620 Pro D"] == devices["Babyface Pro FS"] == "audio_interface"
    # Seven stated versions, and four interfaces from the two Mac flash tools.
    assert len(devices) == 11


@pytest.mark.asyncio
async def test_rme_fails_loudly_without_firmware_items():
    from src.scrapers.plugins.rme import RMEScraper

    scraper = RMEScraper()
    _stub_fetch(scraper, {RMEScraper.DOWNLOADS_URL: _rme_page()})

    assert (await scraper.fetch_device_list()).success is False


RME_INTERFACE_TOOLS = _rme_page(
    _rme_item("Mac OS Flash Update Tool for MADIface XT/XT II/USB/Pro, OctaMic XTC, ADI-2 Pro series &amp; DAC",
              "2026-09-02", "fut_madiface_mac.zip",
              "Update to version: (*latest changes) MADIface XT II: USB 3/2 324, DSP 61, CC 15 "
              "MADIface USB, Hw Rev 6: 25, CC 4 Fireface UFX III: USB 21 DSP 25 CC 47 "
              "Digiface AES: USB 47, MCU 17, CC 11 USB I/O: USB 10 CC 14 USB.MADI: USB 18, CC 13*",
              "MADIface XT II, MADIface USB, Fireface UFX III, Digiface AES, USB.IO, USB.MADI"),
    _rme_item("Windows Flash Update Tool for MADIface XT/XT II/USB/Pro, OctaMic XTC", "2026-09-02",
              "fut_madiface_win.zip", "Update to firmware: MADIface XT II: USB 3/2 323, DSP 61, CC 17 MADIface Pro: 73",
              "MADIface XT II, MADIface Pro"),
    _rme_item("Mac OS Flash Update Tool for Fireface UFX, 802, UCX, UCX II, UC, Babyface/Pro", "2025-09-01",
              "fut_usb_mac.zip",
              "Update to version UFX: 361/163/344/29, 802 A: 20/9/9/12, 802 FS: 227/ 215/ 31, "
              "UCX II (6): 43/36/21, UC: 127/138, Babyface Pro &amp; FS: 211/322.",
              "Babyface Pro, Babyface Pro FS, Fireface 802, Fireface 802 FS, Fireface UC, Fireface UCX II, Fireface UFX"),
    _rme_item("Mac OS X Intel Flash Update Tool for Fireface UFX+ (USB+Thunderbolt)", "2025-08-06", "fut_usb_tb_mac.zip",
              "Update to firmware version USB 55, TB 112, DSP 62 (AKM) and USB 72, TB 167, DSP 62 (ESS).", "Fireface UFX+"),
    _rme_item("macOS UFX+ Flash Update Tool (USB+Thunderbolt)", "2025-02-27", "fut_usb_tb_mac.zip",
              "Update to firmware version USB 55, TB 112, DSP 61 (AKM), USB 72, TB 167, DSP 61 (ESS).", "Fireface UFX+"),
)


def test_rme_reads_interface_revision_lists_from_the_mac_tools():
    """Each list is the version; labels become full names, hardware revisions separate devices."""
    from src.scrapers.plugins.rme import RMEScraper

    products = RMEScraper()._parse_downloads(RME_INTERFACE_TOOLS)
    current = {name: versions[0].version for name, versions in products.items()}

    assert current == {
        "MADIface XT II": "USB 3/2 324, DSP 61, CC 15",
        "MADIface USB (Hw Rev 6)": "25, CC 4",
        "Fireface UFX III": "USB 21, DSP 25, CC 47",
        "Digiface AES": "USB 47, MCU 17, CC 11",
        "USB I/O": "USB 10, CC 14",
        "USB.MADI": "USB 18, CC 13",
        "Fireface UFX": "361/163/344/29",
        "Fireface 802 (Hw Rev A)": "20/9/9/12",
        "Fireface 802 FS": "227/215/31",
        "Fireface UCX II (Hw Rev 6)": "43/36/21",
        "Fireface UC": "127/138",
        "Babyface Pro": "211/322",
        "Babyface Pro FS": "211/322",
        "Fireface UFX+ (AKM)": "USB 55, TB 112, DSP 62",
        "Fireface UFX+ (ESS)": "USB 72, TB 167, DSP 62",
    }


def test_rme_ignores_the_windows_tools_for_interfaces():
    """They order components differently and, for MADIface XT II, state different numbers."""
    from src.scrapers.plugins.rme import RMEScraper

    products = RMEScraper()._parse_downloads(RME_INTERFACE_TOOLS)

    assert [fw.version for fw in products["MADIface XT II"]] == ["USB 3/2 324, DSP 61, CC 15"]
    assert "MADIface Pro" not in products  # only in the Windows tool here


def test_rme_dates_an_interface_only_when_rme_marks_it_changed():
    """A multi-product tool is re-issued when any one product changes, and stars that one."""
    from src.scrapers.plugins.rme import RMEScraper

    products = RMEScraper()._parse_downloads(RME_INTERFACE_TOOLS)

    assert products["USB.MADI"][0].release_date.date().isoformat() == "2026-09-02"
    assert products["Fireface UFX III"][0].release_date is None
    assert products["Babyface Pro FS"][0].release_date is None  # that tool stars nothing


def test_rme_keeps_ufx_plus_history_per_converter_chip():
    """UFX+ tools are for that product alone, so their dates hold, and the older one is history."""
    from src.scrapers.plugins.rme import RMEScraper

    akm = RMEScraper()._parse_downloads(RME_INTERFACE_TOOLS)["Fireface UFX+ (AKM)"]

    assert [(fw.version, fw.release_date.date().isoformat()) for fw in akm] == [
        ("USB 55, TB 112, DSP 62", "2025-08-06"),
        ("USB 55, TB 112, DSP 61", "2025-02-27"),
    ]
