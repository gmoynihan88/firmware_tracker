from datetime import datetime

import pytest

from tests.support import _stub_fetch


def _block(name, month, label, zip_url, notes_html=""):
    accordion = (
        '<div class="accordion"><div id="accordion-2" class="accordion-item">'
        '<a class="accordion-title plain" href="#accordion-item-other-firmware-versions"><span>Other Firmware Versions</span></a>'
        '<div class="accordion-inner"><p>Beta and previous firmware versions are available from Discord.</p></div></div>'
        '<div id="accordion-1" class="accordion-item">'
        '<a class="accordion-title plain" href="#accordion-item-release-notes"><button class="toggle"></button>'
        '<span>Release Notes</span></a>'
        f'<div class="accordion-inner">{notes_html}</div></div></div>'
    )
    return (
        '<div class="row" id="row-1671251764">'
        '<div id="col-60913654" class="col medium-3 small-12 large-3"><div class="col-inner">'
        '<div class="img has-hover"><a href="https://1010music.com/product/x"><img src="x.jpg" /></a></div>'
        f'<h2 style="text-align: center;">{name}</h2>\n<p style="text-align: center;">{month}</p>'
        "</div></div>"
        '<div id="col-1869110234" class="col medium-9 small-12 large-9"><div class="col-inner">'
        '<div class="row row-small" id="row-505542723">'
        f'<div class="col medium-6 small-12 large-6"><div class="col-inner"><p><strong>{label}</strong></p></div></div>'
        f'<div class="col medium-6 small-12 large-6"><div class="col-inner"><a href="{zip_url}" class="button primary">'
        "<span>Download</span></a></div></div></div>"
        f"{accordion}</div></div></div>"
        '<div class="text-center"><div class="is-divider divider clearfix"></div></div>'
    )


UP = "https://1010music.com/wp-content/uploads"
PAGE = (
    '<html><body><h1>Get Firmware Updates and Content Downloads</h1><h1>Desktop Products</h1>'
    + _block("blackbox", "July 2026", "Firmware version 3.1.8", f"{UP}/2026/07/blackbox-3.1.9.zip",
             "<p>Here is what’s new compared to version 3.0.</p><ul><li>DJ FX with XY control</li>"
             "<li>Per pad overdrive algorithm</li></ul>")
    + _block("bluebox<br/>desktop", "August 2026", "Firmware version 1.5.2", f"{UP}/2026/08/bluebox-1.5.2.zip")
    + _block("nanobox<br/>| tangerine", "January 2026", "Firmware version 1.2.8", f"{UP}/2023/12/NANOTANG1228.zip",
             "<h2>Tangerine 1.2.28</h2><p>These new features make tangerine more useful.</p>"
             "<h2>Version 1.2.2</h2><p>New Features</p>")
    + _block("bento factory content", "March 2026", "Factory Patches for 1.3+", "https://download.1010music.com/BentoContentPatchesOnly13RC5.zip")
    + _block("blackbox 2", "", "Firmware version 1.0.1", f"{UP}/2026/07/blackbox2-1.0.1.zip")
    + _block("nanobox<br/>| fireball", "January 2026", "Firmware version 1.2.25", f"{UP}/2023/12/NANOFIRE1225.zip")
    + '<h1>Eurorack Modules</h1>'
    + '<div class="row"><div class="col"><form class="mailpoet_form"><h2 class="mailpoet-heading">DON’T MISS A BEAT</h2>'
      "<p>Get notified about new firmware and products</p></form></div></div>"
    + "</body></html>"
)


def test_1010music_reads_each_product_block_with_its_month_when_it_has_one():
    from src.scrapers.plugins.tenten_music import TenTenMusicScraper

    devices = TenTenMusicScraper()._parse(PAGE)

    assert {name: (fw.version, fw.release_date) for name, fw in devices.items()} == {
        "blackbox": ("3.1.9", datetime(2026, 7, 1)),
        "bluebox desktop": ("1.5.2", datetime(2026, 8, 1)),
        "nanobox | tangerine": ("1.2.28", datetime(2026, 1, 1)),
        "blackbox 2": ("1.0.1", None),
        "nanobox | fireball": ("1.2.25", datetime(2026, 1, 1)),
    }
    assert devices["nanobox | tangerine"].changelog == (
        "Tangerine 1.2.28\nThese new features make tangerine more useful.\nVersion 1.2.2\nNew Features"
    )
    assert devices["blackbox"].changelog == (
        "Here is what’s new compared to version 3.0.\nDJ FX with XY control\nPer pad overdrive algorithm"
    )


def test_1010music_trusts_the_file_over_a_lagging_label():
    from src.scrapers.plugins.tenten_music import TenTenMusicScraper

    scraper = TenTenMusicScraper()

    assert scraper._version("3.1.8", f"{UP}/2026/07/blackbox-3.1.9.zip") == "3.1.9"
    assert scraper._version("1.2.8", f"{UP}/2023/12/NANOTANG1228.zip") == "1.2.28"
    assert scraper._version("1.2.25", f"{UP}/2023/12/NANOFIRE1225.zip") == "1.2.25"
    assert scraper._version("2.3.4", f"{UP}/2024/05/BITBOXMK2234.zip") == "2.3.4"
    assert scraper._version("1.0.1", "https://download.1010music.com/Content.zip") == "1.0.1"


@pytest.mark.asyncio
async def test_1010music_lists_products_from_the_downloads_page():
    from src.scrapers.plugins.tenten_music import TenTenMusicScraper as S
    scraper = S()
    asked = _stub_fetch(scraper, {S.DOWNLOADS_URL: PAGE})

    devices = [d.name for d in (await scraper.fetch_device_list()).devices]
    fireball = await scraper.fetch_firmware_versions("nanobox | fireball", S.DOWNLOADS_URL)

    assert devices == ["blackbox", "bluebox desktop", "nanobox | tangerine", "blackbox 2", "nanobox | fireball"]
    assert [fw.version for fw in fireball.firmware_versions] == ["1.2.25"]
    assert len(asked) == 1


@pytest.mark.asyncio
async def test_1010music_fails_loudly_without_the_downloads_page():
    from src.scrapers.plugins.tenten_music import TenTenMusicScraper as S
    scraper = S()
    _stub_fetch(scraper, {})

    assert (await scraper.fetch_device_list()).success is False
