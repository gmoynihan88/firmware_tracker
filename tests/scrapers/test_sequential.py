import pytest

from tests.support import _stub_fetch


def _seq_page(title, prose, *downloads):
    """An OS page as sequential.com's Elementor theme writes it, storefront header included."""
    buttons = "".join(
        f'<a class="elementor-button" href="https://sequential.com/wp-content/uploads/{href}">'
        f'<span class="elementor-button-content-wrapper"><span class="elementor-button-text">{label}</span></span></a>'
        for label, href in downloads)
    return (
        f"<html><head><title>{title} - Sequential</title></head><body>"
        '<header><a href="/cart/">Cart</a><span class="woocommerce-Price-amount">$ 0.00</span></header>'
        f'<div class="elementor-widget-container"><h1>{title}</h1>{prose}</div>'
        f'<div class="elementor-widget-container">{buttons}</div></body></html>'
    )


REV2 = _seq_page("Prophet Rev2 Operating System",
                 "<p>The current version of the Prophet Rev2 OS is Main 1.2.5</p><h3>IMPORTANT NOTE</h3>"
                 "<p>It is necessary to calibrate the oscillators after you update.</p>",
                 ("Operating System v1.2.5", "Rev2_OS_1.2.5.zip"))

POLY_EVOLVER_RACK = _seq_page("Poly Evolver Rack Operating System",
                              "<p>The current operating system versions are Main 2.1, Voice 2.2 and DSP 3.5.</p>",
                              ("Operating System v2.2", "Poly_Evolver_Rack_OS_M2.1_V2.2_D3.5.zip"))

TEMPEST = _seq_page("Tempest Operating System",
                    "<p>Before updating to OS 1.4, which is the latest OS: Projects and Beats made on previous OS "
                    "versions will load and play correctly on OS 1.4.</p>",
                    ("Operating System v1.6.0.1 (Beta)", "Tempest_OS_1.6.0.1.zip"),
                    ("Operating System v1.5.0.2", "Tempest_OS_1.5.0.2.zip"))

PROPHET_5_10 = _seq_page("Prophet-5/10 Operating System",
                         "<p>The current version of the OS is Main 2.1.0 The current version of the panel OS is Panel 1.1.3</p>",
                         ("Operating System v2.1.0 &amp; v1.1.3", "Prophet-5-10-Main-OS-2.1.0-and-Panel-OS-1.1.3.zip"))

NO_VERSION = _seq_page("Evolver Operating System", "<p>See the ReadMe for installation steps.</p>",
                       ("Operating System Files", "Evolver_OS+ReadMes.zip"))


def test_sequential_reads_main_from_every_way_a_page_states_it():
    from src.scrapers.plugins.sequential import SequentialScraper

    scraper = SequentialScraper()

    def main(text):
        found = scraper._main_version(text)
        return found[0] if found else None

    assert main("The current Main operating system version is 3.0. The latest DSP version is 3.4 or 3.5.") == "3.0"
    assert main("The current Main operating system is version 2.2; DSP is version 3.4") == "2.2"
    assert main("The current version of the Main OS is: Main 1.0.0.1 The current version of the keymech OS is: Keys 1.0.0.2") == "1.0.0.1"
    assert main("The newest version of the Pro 3 Main OS is Pro3_Main_1.2.1.0 The newest version of the Pro 3 Panel OS is Pro3Panel_v1.1.0.13") == "1.2.1.0"
    assert main("The current operating system versions are Main 2.2, Voice 2.2") == "2.2"
    assert main("The current version is Main 1.4.2.3") == "1.4.2.3"
    # A later sentence about an older Main is not the current one.
    assert main("If your Evolver Keyboard is running Main OS 1.5, there is nothing to gain. The current Main operating system is version 2.2") == "2.2"


def test_sequential_takes_main_over_a_download_labelled_with_the_voice_version():
    """Poly Evolver Rack's download says v2.2; that is Voice. Main is 2.1."""
    from src.scrapers.plugins.sequential import SequentialScraper

    name, firmware = SequentialScraper()._parse_page(POLY_EVOLVER_RACK)

    assert (name, firmware.version) == ("Poly Evolver Rack", "2.1")


def test_sequential_reads_the_release_label_when_prose_names_no_main_and_skips_betas():
    """Tempest's prose still calls 1.4 "the latest OS"; the released download is 1.5.0.2, the beta 1.6.0.1."""
    from src.scrapers.plugins.sequential import SequentialScraper

    name, firmware = SequentialScraper()._parse_page(TEMPEST)

    assert (name, firmware.version, firmware.release_date) == ("Tempest", "1.5.0.2", None)
    assert firmware.download_url.endswith("Tempest_OS_1.5.0.2.zip")


def test_sequential_names_the_instrument_from_the_page_title():
    from src.scrapers.plugins.sequential import SequentialScraper

    scraper = SequentialScraper()

    assert scraper._parse_page(PROPHET_5_10)[0] == "Prophet-5/10"
    assert scraper._parse_page(REV2) == ("Prophet Rev2", scraper._parse_page(REV2)[1])
    assert scraper._parse_page(NO_VERSION) is None


@pytest.mark.asyncio
async def test_sequential_lists_only_operating_system_pages_and_invents_no_dates():
    from src.scrapers.plugins.sequential import SequentialScraper as S

    scraper = S()
    listing = (
        '<html><body><a href="https://sequential.com/support/download/prophet-rev2-operating-system/">Rev2 OS</a>'
        '<a href="https://sequential.com/support/download/prophet-rev2-documentation/">Rev2 docs</a>'
        '<a href="/support/download/tempest-operating-system/">Tempest OS</a>'
        '<a href="/support/download/evolver-operating-system/">Evolver OS</a>'
        '<a href="https://sequential.com/support/download/tempest-operating-system/#top">again</a></body></html>'
    )
    asked = _stub_fetch(scraper, {
        S.LISTING_URL: listing,
        S.BASE_URL + "/support/download/prophet-rev2-operating-system/": REV2,
        S.BASE_URL + "/support/download/tempest-operating-system/": TEMPEST,
        S.BASE_URL + "/support/download/evolver-operating-system/": NO_VERSION,
    })

    devices = {d.name: d for d in (await scraper.fetch_device_list()).devices}
    rev2 = await scraper.fetch_firmware_versions("Prophet Rev2", devices["Prophet Rev2"].firmware_page_url)

    assert sorted(devices) == ["Prophet Rev2", "Tempest"]
    assert [(fw.version, fw.release_date) for fw in rev2.firmware_versions] == [("1.2.5", None)]
    assert len(asked) == 4


@pytest.mark.asyncio
async def test_sequential_fails_loudly_without_the_download_listing():
    from src.scrapers.plugins.sequential import SequentialScraper as S

    scraper = S()
    _stub_fetch(scraper, {})

    assert (await scraper.fetch_device_list()).success is False
