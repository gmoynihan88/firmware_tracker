import pytest

from tests.support import _stub_fetch


def _hr_row(label, size="", href="https://cdn.inmusicbrands.com/Software/SGEE/51/file.zip"):
    return (f'<div class="row"> <div class="col">{label}</div> <div class="col">{size}</div> '
            f'<div class="col"><a href="{href}" target="_blank">Download</a> </div> </div>')


def _hr_section(slug, name, *parts):
    return (f'<div class="col-sm-12"> <a class="centerFlex" href="/products/{slug}/index.html"> <h4>{name}</h4> '
            f'<img alt="HeadRush {name}" class="prod-img" src="/assets/images/pdp/{slug}.png"/> </a> {"".join(parts)} </div>')


def _hr_archive(*rows):
    return f'<div class="col-sm-12"> {"".join(rows)} </div>'


def _hr_page(*sections):
    return ('<html><body><h1>HeadRush Downloads</h1><ul><li>Firmware updates</li><li>Product guides</li></ul>'
            f'<div class="container"><div class="row">{"".join(sections)}</div></div>'
            '<div class="col-sm-12"><h4>Sign up for FREE HeadRush Artist Pack Downloads</h4></div></body></html>')


CORE = _hr_section(
    "core", "Core",
    "<!-- Core Firmware v5.1.0) -->",
    _hr_row("HeadRush Core 5.1.0 Firmware Updater (Mac)", "", "https://cdn.inmusicbrands.com/Software/SGEE/51/HeadRush%20Core%205.1.0%20Firmware%20Updater%20-%20Mac.zip"),
    _hr_row("HeadRush Core 5.1.0 Firmware Updater (Win)"),
    _hr_row("READ ME - HeadRush Core Firmware Update Instructions 5.1.0"),
    _hr_row("HeadRush Core - User Guide 5.2.0"),
    "<!-- Core Firmware v5.0.1) -->",
    _hr_row("HeadRush Core 5.0.1 Firmware Updater (Mac)", "(248.5 MB)"),
    _hr_row("READ ME - HeadRush Core Firmware Update Instructions 5.0.1", "(144.1 KB)"),
)

MX5 = _hr_section(
    "mx5", "MX5",
    _hr_row("HeadRush MX5 - Firmware Updater v2.7.0 (Mac)"),
    _hr_row("HeadRush MX5 - Firmware Updater v2.7.0 (Win)"),
    # The live page keeps MX5's older updaters inside a comment: not published.
    f"<!-- {_hr_archive(_hr_row('HeadRush MX5 - Firmware Updater v2.6.0 (Mac)', '(66 MB)'))} -->",
)

VX5 = _hr_section(
    "vx5", "VX5 AutoTune",
    _hr_row("HeadRush VX5 AutoTune - 1.0.0 PC Networking Driver", "(5.3 MB)"),
    _hr_row("HeadRush VX5 AutoTune - Firmware Update 1.3.1 Instructions", "(1.4 MB)"),
    _hr_row("HeadRush VX5 AutoTune - User Guide 1.4"),
)

FRFR_GO = _hr_section("frfr-go", "FRFR-GO", _hr_row("HeadRush FRFR-GO - User Guide v1.0"))

PAGE = _hr_page(VX5, FRFR_GO, CORE, MX5)


def _versions(products, name):
    return [fw.version for fw in products[name]]


def test_headrush_reads_every_updater_in_a_section_and_not_the_user_guide():
    """Core's user guide says 5.2.0; its newest firmware is 5.1.0."""
    from src.scrapers.plugins.headrush import HeadRushScraper

    products = HeadRushScraper()._parse_page(PAGE)

    assert _versions(products, "HeadRush Core") == ["5.1.0", "5.0.1"]
    assert products["HeadRush Core"][0].download_url.endswith("5.1.0%20Firmware%20Updater%20-%20Mac.zip")
    assert all(fw.release_date is None for fw in products["HeadRush Core"])


def test_headrush_reads_both_updater_label_shapes_but_not_commented_out_releases():
    """ "MX5 - Firmware Updater v2.7.0"; its v2.6.0 is hidden in a comment the vendor has not published."""
    from src.scrapers.plugins.headrush import HeadRushScraper

    products = HeadRushScraper()._parse_page(PAGE)

    assert _versions(products, "HeadRush MX5") == ["2.7.0"]


def test_headrush_reads_the_instructions_only_when_a_product_has_no_updater():
    """VX5 AutoTune lists instructions for 1.3.1 beside a 1.0.0 networking driver."""
    from src.scrapers.plugins.headrush import HeadRushScraper

    products = HeadRushScraper()._parse_page(PAGE)

    assert _versions(products, "HeadRush VX5 AutoTune") == ["1.3.1"]
    # Core has updaters, so its instructions add nothing of their own.
    assert "HeadRush FRFR-GO" not in products


@pytest.mark.asyncio
async def test_headrush_lists_firmware_products_from_one_fetch():
    from src.scrapers.plugins.headrush import HeadRushScraper as H

    scraper = H()
    asked = _stub_fetch(scraper, {H.DOWNLOADS_URL: PAGE})

    devices = {d.name: d.category for d in (await scraper.fetch_device_list()).devices}
    core = await scraper.fetch_firmware_versions("HeadRush Core", H.DOWNLOADS_URL)

    assert asked == [H.DOWNLOADS_URL]
    assert devices == {"HeadRush VX5 AutoTune": "guitar_pedal", "HeadRush Core": "guitar_pedal", "HeadRush MX5": "guitar_pedal"}
    assert core.firmware_versions[0].version == "5.1.0"


@pytest.mark.asyncio
async def test_headrush_fails_loudly_without_any_updater():
    from src.scrapers.plugins.headrush import HeadRushScraper as H

    scraper = H()
    _stub_fetch(scraper, {H.DOWNLOADS_URL: _hr_page(FRFR_GO)})

    assert (await scraper.fetch_device_list()).success is False
