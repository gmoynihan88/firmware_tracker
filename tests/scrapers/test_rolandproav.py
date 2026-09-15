import pytest


def _listing(*links):
    return "".join(f'<a href="/global/support/by_product/x/updates_drivers/{i}/">{text}</a>' for i, text in enumerate(links))


def test_rolandproav_reads_each_wording_of_the_firmware_link():
    """"System Program" alone missed M-480, M-400, M-380 and M-48."""
    from src.scrapers.plugins.rolandproav import RolandProAVScraper

    link = RolandProAVScraper()._system_program_link

    assert link(_listing("M-5000 System Program (Ver.1.520)"))[0] == "1.520"
    assert link(_listing("M-480 System Update Ver.1.610", "M-480 RCS Ver.1.610 for Windows"))[0] == "1.610"
    assert link(_listing("M-400 System Software Update Ver.2.321", "M-400 RCS Ver.2.321 for Windows"))[0] == "2.321"
    assert link(_listing("M-48 System Update Version 1.010", "S-4000 RCS Ver.2.400 for Windows"))[0] == "1.010"
    # Numbered by date, as Roland publishes it.
    assert link(_listing("UVC-01 System Program (Ver.2024.06.11) for Windows"))[0] == "2024.06.11"


def test_rolandproav_does_not_take_the_editor_or_a_driver_for_firmware():
    from src.scrapers.plugins.rolandproav import RolandProAVScraper

    page = _listing(
        "M-480 RCS Ver.1.610 for Windows",
        "V-Mixer Driver Ver.1.0.1 for Windows 10/11",
        "M-400/M-380 USB Driver Version 1.0.1 for Windows 8 and 8.1",
        "Roland Live Recorder Ver.3.0.0 for Windows ( 64-bit Edition )",
    )

    assert RolandProAVScraper()._system_program_link(page) is None


@pytest.mark.asyncio
async def test_rolandproav_lists_products_with_firmware_from_the_index():
    from src.scrapers.plugins.rolandproav import RolandProAVScraper

    base = "https://proav.roland.com/global/support"
    index = (
        '<ul class="link-group">'
        '<li><a href="/global/support/by_product/m-480/updates_drivers/"><h5>M-480 <small>48-Channel Live Digital Mixing Console</small></h5></a></li>'
        '<li><a href="/global/support/by_product/cgm-30/updates_drivers/"><h5>CGM-30 <small>Gooseneck Microphone</small></h5></a></li>'
        "</ul>"
    )
    pages = {
        f"{base}/updates_drivers/": index,
        f"{base}/by_product/m-480/updates_drivers/": '<a href="/global/support/by_product/m-480/updates_drivers/23c1/">M-480 System Update Ver.1.610</a>',
        f"{base}/by_product/m-480/updates_drivers/23c1/": '<div class="details">[ Ver.1.610 ] MAR 2024 Fixed an issue. [ Ver.1.600 ] JUN 2022 Added scenes.</div>',
        f"{base}/by_product/cgm-30/updates_drivers/": "<p>Owner's manual only.</p>",
    }
    scraper = RolandProAVScraper(full_sweep=True)

    async def _page(url, *_args, **_kwargs):
        return pages.get(url)

    scraper.fetch_page = _page
    listing = await scraper.fetch_device_list()

    assert [d.name for d in listing.devices] == ["M-480"]
    versions = (await scraper.fetch_firmware_versions("M-480", listing.devices[0].firmware_page_url)).firmware_versions
    assert [(fw.version, fw.release_date.strftime("%Y-%m")) for fw in versions] == [("1.610", "2024-03"), ("1.600", "2022-06")]


def test_rolandproav_checks_every_product_every_run():
    from src.scrapers.plugins.rolandproav import RolandProAVScraper

    assert RolandProAVScraper.BATCHES == 1
