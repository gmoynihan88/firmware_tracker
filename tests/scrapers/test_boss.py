def test_boss_picks_the_system_program_over_the_editor_and_drivers():
    """A Boss page offers a System Program, a Tone Studio editor, drivers and Chromium.

    SY-300 has eleven version-bearing links and not one is firmware -- all editor and
    driver builds -- so the right answer there is nothing at all.
    """
    from src.scrapers.plugins.boss import BossScraper

    firmware_page = """
      <a href="/x/">BOSS TONE STUDIO for KATANA Mk II Ver.2.1.0 for Windows</a>
      <a href="/y/">KATANA Mk II System Program (Ver.2.00)</a>
      <a href="/z/">KATANA Driver Ver.1.0.1 for macOS Sonoma 14.x later</a>
      <a href="/c/">Source code of CEF(Chromium Embedded Framework) Version 3.3683.1920</a>
    """
    version, url = BossScraper()._system_program_link(firmware_page)
    assert version == "2.00"
    assert url.endswith("/y/")

    editor_only = """
      <a href="/x/">BOSS TONE STUDIO for SY-300 Ver.1.1.1 for Windows</a>
      <a href="/z/">SY-300 Driver Ver.1.0.2 for Windows 10/11</a>
    """
    assert BossScraper()._system_program_link(editor_only) is None


import pytest


@pytest.mark.asyncio
async def test_boss_lists_index_products_under_the_databases_names():
    """The index writes KATANA in capitals; the catalogued rows do not."""
    from src.scrapers.plugins.boss import BossScraper

    index = (
        '<ul class="link-group">'
        '<li><a href="/us/support/by_product/katana-100_mk2/updates_drivers/"><h5>KATANA-100 MkII <small>Guitar Amplifier</small></h5></a></li>'
        '<li><a href="/us/support/by_product/rc-600/updates_drivers/"><h5>RC-600 <small>Loop Station</small></h5></a></li>'
        "</ul>"
    )
    pages = {
        "https://www.boss.info/us/support/updates_drivers/": index,
        "https://www.boss.info/us/support/by_product/katana-100_mk2/updates_drivers/": '<a href="/k/">KATANA Mk II System Program (Ver.2.00)</a>',
        "https://www.boss.info/us/support/by_product/rc-600/updates_drivers/": '<a href="/r/">RC-600 System Program (Ver.1.60)</a>',
    }
    scraper = BossScraper(full_sweep=True)

    async def _page(url, *_args, **_kwargs):
        return pages.get(url)

    scraper.fetch_page = _page
    devices = {d.name: d.category for d in (await scraper.fetch_device_list()).devices}

    assert devices == {"Katana-100 MkII": "other", "RC-600": "guitar_pedal"}


def test_boss_files_products_by_their_subtitle():
    from src.scrapers.plugins.boss import BossScraper

    category = BossScraper()._category
    assert category("Guitar Effects Processor") == "guitar_pedal"
    assert category("Loop Station") == "guitar_pedal"
    assert category("Guitar Amplifier") == "other"
    assert category("Digital Recorder") == "other"
    assert category("Wireless MIDI Expression Pedal") == "midi_controller"
    assert category("Dr. Rhythm") == "synthesizer"
