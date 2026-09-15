ROLAND_LISTING = """
<h5><a href="/global/support/by_product/mc-101/updates_drivers/abc/">MC-101 System Program (Ver.1.82)</a></h5>
<h5><a href="/d1/">MC-101 Driver Ver.1.0.3 for macOS Sonoma 14.x or later</a></h5>
<h5><a href="/d2/">MC-101 Driver Ver.1.0.2 for Windows 10/11</a></h5>
"""


ROLAND_DETAIL = """
<div class="details">
  <b>HOW TO TELL THE VERSION</b>
  Before you start, check the system program version of your MC-101.
  <b>UPDATE HISTORY</b>
  [ Ver.1.82 ] JUN 2023 Bug Fixes. Arpeggiator fix.
  [ Ver.1.81 ] NOV 2022 Bug Fixes. SDZ loading fix.
</div>
"""


def test_roland_picks_the_system_program_not_a_driver():
    """The listing puts USB drivers beside the firmware, both written "Ver.".

    A pattern taking the first version on the page can land on Ver.1.0.3, which is a
    macOS driver rather than anything the instrument runs.
    """
    from src.scrapers.plugins.roland import RolandScraper

    version, url = RolandScraper()._system_program_link(ROLAND_LISTING)

    assert version == "1.82"
    assert url.endswith("/mc-101/updates_drivers/abc/")


def test_roland_accepts_the_bare_system_program_form():
    """AIRA Compacts write it without parentheses.

    Requiring them silently returned nothing for J-6 and T-8, which do publish
    firmware -- a stricter pattern reading as "this product has none".
    """
    from src.scrapers.plugins.roland import RolandScraper

    bare = '<a href="/x/">J-6 System Program Ver.1.02</a>'
    assert RolandScraper()._system_program_link(bare)[0] == "1.02"

    spaced = '<a href="/x/">JUPITER-X System Program ( Ver.3.03 )</a>'
    assert RolandScraper()._system_program_link(spaced)[0] == "3.03"


def test_roland_reads_the_whole_update_history():
    """The detail page carries every release, not just the current one.

    Roland dates to the month, stored as the first of it.
    """
    from src.scrapers.plugins.roland import RolandScraper

    versions = RolandScraper()._parse_history(ROLAND_DETAIL)

    assert [f.version for f in versions] == ["1.82", "1.81"]
    assert versions[0].release_date.strftime("%Y-%m-%d") == "2023-06-01"
    assert versions[1].release_date.strftime("%Y-%m-%d") == "2022-11-01"
    # Each entry keeps its own notes rather than the whole page.
    assert "Arpeggiator" in versions[0].changelog
    assert "Arpeggiator" not in versions[1].changelog
    # The "how to tell the version" prose above the history is not a release.
    assert len(versions) == 2


def test_boss_and_roland_share_one_parser():
    """Boss is a Roland brand and the pages are identical in shape.

    Verified by running Roland's link finder against a real Boss page before the
    parsing was moved into a mixin both use.
    """
    from src.scrapers.plugins.boss import BossScraper
    from src.scrapers.plugins.roland import RolandScraper
    from src.scrapers.roland_group import SystemProgramMixin

    assert issubclass(BossScraper, SystemProgramMixin)
    assert issubclass(RolandScraper, SystemProgramMixin)


import pytest
from unittest.mock import patch


def _index(entries):
    """The Updates & Drivers index as served: an A-Z run of link groups."""
    items = "".join(
        f'<li>\n<a href="/global/support/by_product/{slug}/updates_drivers/"><h5>{name} <small>{subtitle}</small></h5></a>\n</li>'
        for slug, name, subtitle in entries
    )
    return f'<h4>A</h4><ul class="link-group">{items}</ul><a href="/global/support/">Support</a>'


def _listing(name, version=None, detail="/detail/"):
    firmware = f'<h5><a href="{detail}">{name} System Program (Ver.{version})</a></h5>' if version else ""
    return f'{firmware}<h5><a href="/drv/">{name} Driver Ver.1.0.3 for macOS</a></h5>'


INDEX = _index([
    ("mc-101", "MC-101", "GROOVEBOX"),
    ("um-one", "UM-ONE", "USB MIDI Interface"),
    ("fp-30x", "FP-30X", "Digital Piano"),
])

PAGES = {
    "https://www.roland.com/global/support/updates_drivers/": INDEX,
    "https://www.roland.com/global/support/by_product/mc-101/updates_drivers/": _listing("MC-101", "1.82", "/global/support/by_product/mc-101/updates_drivers/sp/"),
    "https://www.roland.com/global/support/by_product/mc-101/updates_drivers/sp/": ROLAND_DETAIL,
    # Drivers only: no firmware, not listed.
    "https://www.roland.com/global/support/by_product/um-one/updates_drivers/": _listing("UM-ONE"),
    # A System Program whose detail page has no history keeps the listed version.
    "https://www.roland.com/global/support/by_product/fp-30x/updates_drivers/": _listing("FP-30X", "1.05", "/global/support/by_product/fp-30x/updates_drivers/sp/"),
    "https://www.roland.com/global/support/by_product/fp-30x/updates_drivers/sp/": "<div class='details'>Download</div>",
}


def _scraper(pages=PAGES, full_sweep=True):
    from src.scrapers.plugins.roland import RolandScraper

    scraper = RolandScraper(full_sweep=full_sweep)
    fetched = []

    async def _page(url, *_args, **_kwargs):
        fetched.append(url)
        return pages.get(url)

    scraper.fetch_page = _page
    return scraper, fetched


def test_roland_reads_name_url_and_subtitle_from_the_index():
    from src.scrapers.plugins.roland import RolandScraper

    products = RolandScraper()._index_products(INDEX)

    assert products[0] == (
        "MC-101", "https://www.roland.com/global/support/by_product/mc-101/updates_drivers/", "GROOVEBOX",
    )
    assert len(products) == 3


@pytest.mark.asyncio
async def test_roland_lists_only_index_products_that_publish_a_system_program():
    """UM-ONE's page offers drivers only, so a row for it would never report."""
    scraper, _ = _scraper()

    devices = {d.name: d for d in (await scraper.fetch_device_list()).devices}

    assert set(devices) == {"MC-101", "FP-30X"}
    assert devices["MC-101"].product_url == "https://www.roland.com/global/products/mc-101/"
    assert devices["MC-101"].category == "synthesizer"

    mc = await scraper.fetch_firmware_versions("MC-101", devices["MC-101"].firmware_page_url)
    assert [f.version for f in mc.firmware_versions] == ["1.82", "1.81"]
    fp = await scraper.fetch_firmware_versions("FP-30X", devices["FP-30X"].firmware_page_url)
    assert [f.version for f in fp.firmware_versions] == ["1.05"]


@pytest.mark.asyncio
async def test_roland_reads_each_page_once_per_scrape():
    scraper, fetched = _scraper()

    listing = await scraper.fetch_device_list()
    for device in listing.devices:
        await scraper.fetch_firmware_versions(device.name, device.firmware_page_url)

    assert sorted(fetched) == sorted(PAGES)


def test_roland_batches_are_even_and_cover_the_index_once():
    """580 products in six batches: a predictable ceiling on every run."""
    from src.scrapers.plugins.roland import RolandScraper

    products = [(f"P{i}", f"https://www.roland.com/global/support/by_product/p{i:03d}/updates_drivers/", "") for i in range(580)]
    scraper = RolandScraper()
    seen, sizes = [], []
    for day in range(scraper.BATCHES):
        with patch.object(RolandScraper, "_today_batch", lambda self, d=day: d):
            batch = scraper._select_batch(list(reversed(products)))
        sizes.append(len(batch))
        seen.extend(url for _n, url, _s in batch)

    assert max(sizes) - min(sizes) <= 1
    assert sorted(seen) == sorted(url for _n, url, _s in products)
    assert len(RolandScraper(full_sweep=True)._select_batch(products)) == 580


@pytest.mark.asyncio
async def test_roland_reports_not_checked_outside_todays_batch():
    """An empty success would claim a catalogued product publishes nothing."""
    scraper, fetched = _scraper(full_sweep=False)

    with patch.object(type(scraper), "_today_batch", lambda self: 0):
        listing = await scraper.fetch_device_list()
        names = {d.name for d in listing.devices}
        # Sorted by URL and strided by six: only the first of these three is today's.
        assert names == {"FP-30X"}
        result = await scraper.fetch_firmware_versions("MC-101", "")

    assert result.success is True and result.not_checked is True
    assert "https://www.roland.com/global/support/by_product/mc-101/updates_drivers/" not in fetched


def test_roland_full_sweep_reads_the_environment(monkeypatch):
    from src.scrapers.plugins.roland import RolandScraper

    monkeypatch.setenv("ROLAND_FULL_SWEEP", "1")
    assert RolandScraper()._full_sweep is True
    monkeypatch.delenv("ROLAND_FULL_SWEEP")
    assert RolandScraper()._full_sweep is False


@pytest.mark.asyncio
async def test_roland_fails_rather_than_dropping_a_product():
    missing = dict(PAGES)
    del missing["https://www.roland.com/global/support/by_product/fp-30x/updates_drivers/"]
    assert (await _scraper(missing)[0].fetch_device_list()).success is False

    assert (await _scraper({})[0].fetch_device_list()).success is False
    no_products = {"https://www.roland.com/global/support/updates_drivers/": "<p>Updates &amp; Drivers</p>"}
    assert (await _scraper(no_products)[0].fetch_device_list()).success is False


def test_roland_files_products_by_their_subtitle():
    from src.scrapers.plugins.roland import RolandScraper

    category = RolandScraper()._category
    assert category("Digital Piano") == "synthesizer"
    assert category("V-Drums") == "synthesizer"
    assert category("USB Audio Interface") == "audio_interface"
    assert category("Audio Interface & MIDI Keyboard Controller") == "midi_controller"
    assert category("Expression Pedal") == "midi_controller"
    assert category("Guitar Amplifier") == "other"
    # "Keyboard" is a synth word; the amplifier rule has to come first.
    assert category("Keyboard Amplifier") == "other"
    assert category("Dual Bus Streaming Mixer") == "other"
