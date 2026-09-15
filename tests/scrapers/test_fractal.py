import pytest

from tests.support import _stub_fetch


def _fractal_page(title, tail="Compatible with all models – June 25, 2026") -> str:
    return f"""
    <div class="w-iconbox"><div class="w-iconbox-meta">
      <h3 class="w-iconbox-title">{title}</h3><p>{tail}</p>
    </div></div>
    <div class="w-iconbox"><div class="w-iconbox-meta">
      <h3 class="w-iconbox-title">USB Firmware Update 1.04</h3><p>Separate chip.</p>
    </div></div>
    """


def test_fractal_reads_all_three_firmware_wordings():
    """A pattern fitted to one silently drops the other two."""
    from src.scrapers.plugins.fractal import FractalAudioScraper as F

    scraper = F()
    for title, expected in (
        ("Firmware 32.06", "32.06"),
        ("Firmware v12.0", "12.0"),
        ("AX8 Firmware Quantum 10.01", "10.01"),
    ):
        parsed = scraper._parse_product(_fractal_page(title))
        assert [fw.version for fw in parsed] == [expected], title


def test_fractal_refuses_the_usb_chips_firmware():
    """"USB Firmware Update 1.04" sits in the same list on the FM9 page."""
    from src.scrapers.plugins.fractal import FractalAudioScraper as F

    parsed = F()._parse_product(_fractal_page("Firmware v12.0"))

    assert [fw.version for fw in parsed] == ["12.0"]
    assert "1.04" not in {fw.version for fw in parsed}


def test_fractal_reads_the_date_from_the_line_below():
    from src.scrapers.plugins.fractal import FractalAudioScraper as F

    parsed = F()._parse_product(_fractal_page("Firmware 32.06"))

    assert parsed[0].release_date.strftime("%Y-%m-%d") == "2026-06-25"
    undated = F()._parse_product(_fractal_page("Firmware 5.03", tail="No date here."))
    assert undated[0].release_date is None


@pytest.mark.asyncio
async def test_fractal_lists_only_products_whose_firmware_it_could_read():
    """Axe-Fx II states its firmware in a shape none of the patterns match.

    Listing it would add a row reporting nothing on every run.
    """
    from src.scrapers.plugins.fractal import FractalAudioScraper as F

    home = ('<a href="https://www.fractalaudio.com/fm9-downloads/">FM9</a>'
            '<a href="https://www.fractalaudio.com/axe-fx-ii-downloads/">II</a>')
    pages = {
        "https://www.fractalaudio.com/": home,
        "https://www.fractalaudio.com/fm9-downloads/": _fractal_page("Firmware v12.0"),
        "https://www.fractalaudio.com/axe-fx-ii-downloads/": "<p>Downloads coming soon</p>",
    }
    scraper = F()
    _stub_fetch(scraper, pages)

    devices = await scraper.fetch_device_list()

    assert [d.name for d in devices.devices] == ["FM9"]
    assert "Axe-Fx II" not in {d.name for d in devices.devices}


@pytest.mark.asyncio
async def test_fractal_fetches_each_page_once_across_both_calls():
    from src.scrapers.plugins.fractal import FractalAudioScraper as F

    pages = {
        "https://www.fractalaudio.com/": '<a href="/fm9-downloads/">FM9</a>',
        "https://www.fractalaudio.com/fm9-downloads/": _fractal_page("Firmware v12.0"),
    }
    scraper = F()
    asked = _stub_fetch(scraper, pages)

    await scraper.fetch_device_list()
    await scraper.fetch_firmware_versions("FM9", "")

    assert len(asked) == 2  # the homepage, then the one product page


@pytest.mark.asyncio
async def test_fractal_fails_when_the_homepage_links_nothing():
    from src.scrapers.plugins.fractal import FractalAudioScraper as F

    scraper = F()
    _stub_fetch(scraper, {"https://www.fractalaudio.com/": "<p>hello</p>"})

    assert (await scraper.fetch_device_list()).success is False
