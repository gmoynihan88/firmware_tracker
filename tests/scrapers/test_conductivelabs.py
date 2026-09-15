from datetime import datetime

import pytest

from tests.support import _stub_fetch

UP = "https://conductivelabs.com/wp-content/uploads"

NDLR = (
    '<html><body><div class="col-md-7 col-sm-12 col-xs-12 col-lg-7"> <h2 class="color1-color">The NDLR Firmware Update</h2>'
    '<p class="">Conductive Labs may provide periodic updates to The NDLR firmware.</p>'
    '<p class="" style="margin-left: 41px;"><strong>Only for the original version of The NDLR (rev1) with a blue/grey base '
    "(not red base).<br /> Download the latest The NDLR rev1 Firmware Update here:</strong></p>"
    '<p class="" style="margin-left: 41px;"><span style="text-decoration: underline;">'
    f'<a style="color: #800080;" href="{UP}/2023/10/NDLRv1.1.086.zip">NDLRv1.1.086</a>.zip</span> (Oct 27, 2023)</p>'
    '<p class="">You can check the firmware version by going to the System 3 menu on The NDLR.</p>'
    '<p class="" style="margin-left: 41px;"><strong>Firmware update for The NDLR rev2 with the powder coated '
    '<span style="color: #ff0000;">RED</span> base and power button.</strong></p>'
    '<p class="" style="margin-left: 41px;"><span style="text-decoration: underline;">'
    f'<a href="{UP}/2025/08/NDLR_Rev2_firmware_v3_3_6.zip">NDLR_Rev2_firmware_v3_3_6</a></span> (August 6, 2025)<br />'
    " Note that Release 3 firmware for The NDLR Rev2 has many feature additions and changes.</p>"
    '<p class="" style="margin-left: 38px;"><strong>If you need to use the previous version release 2 firmware for '
    "The NDLR Rev2, here it is:</strong></p>"
    '<p class="" style="margin-left: 41px;"><span style="text-decoration: underline;">'
    f'<a style="color: #800080;" href="{UP}/2023/10/NDLRv2.0.014.zip">NDLRv2.0.014</a>.zip</span> (Oct 27, 2023)</p>'
    "</div></body></html>"
)

MRCC = (
    '<html><body><article><div class="entry-content"><div class="heading">'
    '<h5 class="">Conductive Labs provides periodic updates to MRCC firmware.</h5>'
    '<h5 class="">If your MRCC firmware is less than version 1.1.077, updating is mandatory.</h5>'
    '<p class=""><strong>Download the latest MRCC Firmware Update Here: '
    f'<a href="{UP}/2025/10/MRCC_1.1.095_09-10-2025.zip">MRCC_1.1.095_09-10-2025</a></strong></p>'
    '<p class=""><a href="#mrcc-firmware-update-instructions">Jump to Firmware installation instructions</a></p>'
    '<p class="">Changes include the following:</p>'
    '<ul class=""><li><strong>Features:</strong></li><li>Number of simultaneous routes increased from 50 to 255.</li></ul>'
    '<p class=""><strong><span class="mycode_b">Fixes:</span></strong></p>'
    '<ul class=""><li>MRCC MIDI Cntrl Port won&#8217;t save when greater than P06.</li></ul>'
    '<h4 id="mrcc-firmware-update-instructions">MRCC Firmware Update Instructions:</h4>'
    '<ul><li>Download the zip file and unzip it.</li></ul>'
    "</div></div></article></body></html>"
)

INDEX = (
    '<html><body><a href="https://conductivelabs.com/download/">Downloads</a>'
    '<a href="https://conductivelabs.com/download/the-ndlr-firmware-updates-and-instructions/">The NDLR Firmware Update</a>'
    '<a href="https://conductivelabs.com/download/mrcc-firmware-update/">MRCC Firmware Update</a>'
    '<a href="https://conductivelabs.com/download/mrcc-firmware-update/#mrcc-firmware-update-instructions">again</a>'
    '<a href="https://conductivelabs.com/download/the-ndlr-manual/">Manual</a></body></html>'
)


def test_conductivelabs_gives_each_ndlr_file_to_the_revision_named_before_it():
    from src.scrapers.plugins.conductivelabs import ConductiveLabsScraper

    firmware = ConductiveLabsScraper()._parse_page(NDLR)

    assert {name: [(r.version, r.release_date, r.changelog) for r in rs] for name, rs in firmware.items()} == {
        "The NDLR Rev1": [("1.1.086", datetime(2023, 10, 27), None)],
        "The NDLR Rev2": [("3.3.6", datetime(2025, 8, 6), None), ("2.0.014", datetime(2023, 10, 27), None)],
    }


def test_conductivelabs_leaves_an_ambiguous_file_name_date_undated_and_reads_its_notes():
    from src.scrapers.plugins.conductivelabs import ConductiveLabsScraper

    mrcc = ConductiveLabsScraper()._parse_page(MRCC)["MRCC"]

    assert [(r.version, r.release_date) for r in mrcc] == [("1.1.095", None)]
    assert mrcc[0].changelog.splitlines() == [
        "Features:", "Number of simultaneous routes increased from 50 to 255.",
        "Fixes:", "MRCC MIDI Cntrl Port won’t save when greater than P06.",
    ]


@pytest.mark.asyncio
async def test_conductivelabs_reads_every_firmware_page_the_index_links():
    from src.scrapers.plugins.conductivelabs import ConductiveLabsScraper as S

    scraper = S()
    ndlr_url = "https://conductivelabs.com/download/the-ndlr-firmware-updates-and-instructions/"
    mrcc_url = "https://conductivelabs.com/download/mrcc-firmware-update/"
    asked = _stub_fetch(scraper, {S.INDEX_URL: INDEX, ndlr_url: NDLR, mrcc_url: MRCC})

    devices = {d.name: (d.category, d.firmware_page_url) for d in (await scraper.fetch_device_list()).devices}
    rev2 = await scraper.fetch_firmware_versions("The NDLR Rev2", ndlr_url)

    assert devices == {"The NDLR Rev1": ("midi_controller", ndlr_url), "The NDLR Rev2": ("midi_controller", ndlr_url),
                       "MRCC": ("midi_controller", mrcc_url)}
    assert [r.version for r in rev2.firmware_versions] == ["3.3.6", "2.0.014"]
    assert len(asked) == 3


@pytest.mark.asyncio
async def test_conductivelabs_fails_loudly_without_the_index():
    from src.scrapers.plugins.conductivelabs import ConductiveLabsScraper as S

    scraper = S()
    _stub_fetch(scraper, {})

    assert (await scraper.fetch_device_list()).success is False
