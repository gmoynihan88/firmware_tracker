import pytest


def test_ni_parses_version_from_thread_title():
    """The current version is read out of the update thread's title."""
    from src.scrapers.plugins.native_instruments import NativeInstrumentsScraper

    scraper = NativeInstrumentsScraper()
    cases = [
        ("Official update status - Kontakt (current version: 8.13.0)", "Kontakt", "8.13.0"),
        # Absynth's and Ozone's threads omit the colon.
        ("Official update status - Absynth 6 (current version 6.1)", "Absynth 6", "6.1"),
        ("Official update status - Guitar Rig 7 (current version: 7.0.2)", "Guitar Rig 7", "7.0.2"),
    ]
    for title, product, version in cases:
        match = scraper.TITLE_VERSION.search(title)
        assert match, title
        assert match.group("product").strip() == product
        assert match.group("version").strip() == version


SITEMAP_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://community.native-instruments.com/sitemap-category-kontakt-6001-1000.xml</loc></sitemap>
<sitemap><loc>https://community.native-instruments.com/sitemap-category-maschine-1001-1000.xml</loc></sitemap>
</sitemapindex>"""

SITEMAPS = {
    "https://community.native-instruments.com/sitemap-category-kontakt-6001-1000.xml": """
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://community.native-instruments.com/discussion/39/official-update-status-kontakt-current-version-8-13-0</loc></url>
<url><loc>https://community.native-instruments.com/discussion/41200/kontakt-8-crashes-after-update</loc></url>
</urlset>""",
    "https://community.native-instruments.com/sitemap-category-maschine-1001-1000.xml": """
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://community.native-instruments.com/discussion/40/official-update-status-maschine-3-current-version-3-6-0</loc></url>
<url><loc>https://community.native-instruments.com/discussion/3040/official-update-status-maschine-current-version-2-2-0</loc></url>
</urlset>""",
}

# The slug of thread 3040 still says "maschine"; its title says Maschine +.
DISCUSSIONS = {
    "39": {"discussionID": 39, "name": "Official update status - Kontakt (current version: 8.13.0)"},
    "40": {"discussionID": 40, "name": "Official update status - Maschine 3 (current version: 3.6.0)"},
    "3040": {"discussionID": 3040, "name": "Official update status - Maschine + (current version 2.2.0)"},
}


def _scraper(sitemaps=None, discussions=None):
    from src.scrapers.plugins.native_instruments import NativeInstrumentsScraper

    scraper = NativeInstrumentsScraper()
    pages = {scraper.SITEMAP_INDEX: SITEMAP_INDEX, **(SITEMAPS if sitemaps is None else sitemaps)}
    threads = DISCUSSIONS if discussions is None else discussions

    async def _page(url, *_args, **_kwargs):
        return pages.get(url)

    async def _json(url, *_args, **_kwargs):
        return threads.get(url.rsplit("/", 1)[-1])

    scraper.fetch_page = _page
    scraper.fetch_json = _json
    return scraper


@pytest.mark.asyncio
async def test_ni_lists_every_update_thread_the_sitemaps_hold():
    """The products are the update threads, not a hand-kept list of forty."""
    scraper = _scraper()

    result = await scraper.fetch_device_list()

    assert result.success is True
    devices = {d.name: d for d in result.devices}
    assert list(devices) == ["Kontakt 8", "Maschine 3", "Maschine+"]
    assert devices["Maschine 3"].firmware_page_url == "https://community.native-instruments.com/discussion/40"
    assert devices["Maschine+"].category == "synthesizer"
    assert devices["Kontakt 8"].category == "vst_plugin"


@pytest.mark.asyncio
async def test_ni_names_a_product_by_the_major_its_title_leaves_out():
    """"Kontakt (current version: 9.0.0)" is Kontakt 9, not an update to Kontakt 8."""
    nine = dict(DISCUSSIONS, **{"39": {"name": "Official update status - Kontakt (current version: 9.0.0)"}})
    scraper = _scraper(discussions=nine)

    names = [d.name for d in (await scraper.fetch_device_list()).devices]

    assert "Kontakt 9" in names and "Kontakt 8" not in names
    # A title that already carries its major is left alone.
    assert "Maschine 3" in names


@pytest.mark.asyncio
async def test_ni_reads_the_version_from_the_thread_title():
    scraper = _scraper()

    result = await scraper.fetch_firmware_versions("Maschine+", "https://community.native-instruments.com/discussion/3040")

    assert result.success is True
    firmware = result.firmware_versions[0]
    assert firmware.version == "2.2.0"
    assert firmware.download_url == "https://community.native-instruments.com/discussion/3040"
    assert firmware.changelog == "Reported by NI as current for Maschine +."


@pytest.mark.asyncio
async def test_ni_fails_rather_than_dropping_threads():
    """A sitemap or a thread that does not load would silently remove a product."""
    missing_sitemap = dict(SITEMAPS)
    del missing_sitemap["https://community.native-instruments.com/sitemap-category-maschine-1001-1000.xml"]
    assert (await _scraper(sitemaps=missing_sitemap).fetch_device_list()).success is False

    missing_thread = dict(DISCUSSIONS)
    del missing_thread["40"]
    assert (await _scraper(discussions=missing_thread).fetch_device_list()).success is False

    retitled = dict(DISCUSSIONS, **{"40": {"name": "Maschine 3 release notes"}})
    assert (await _scraper(discussions=retitled).fetch_device_list()).success is False

    no_threads = {url: "<urlset></urlset>" for url in SITEMAPS}
    assert (await _scraper(sitemaps=no_threads).fetch_device_list()).success is False


@pytest.mark.asyncio
async def test_ni_reports_no_version_for_a_product_without_a_thread():
    """Kontakt 7, Raum and the old static list keep their rows but have nothing to read."""
    scraper = _scraper()

    result = await scraper.fetch_firmware_versions("Raum", "https://www.native-instruments.com/en/products/komplete/effects/raum/")

    assert result.success is True
    assert result.firmware_versions == []


@pytest.mark.asyncio
async def test_ni_reads_each_sitemap_and_thread_once_per_scrape():
    from src.scrapers.plugins.native_instruments import NativeInstrumentsScraper

    scraper = _scraper()
    calls = []
    page, json_ = scraper.fetch_page, scraper.fetch_json

    async def _page(url, *a, **k):
        calls.append(url)
        return await page(url, *a, **k)

    async def _json(url, *a, **k):
        calls.append(url)
        return await json_(url, *a, **k)

    scraper.fetch_page, scraper.fetch_json = _page, _json

    listing = await scraper.fetch_device_list()
    for device in listing.devices:
        await scraper.fetch_firmware_versions(device.name, device.firmware_page_url)

    assert len(calls) == len(set(calls)) == 1 + len(SITEMAPS) + len(DISCUSSIONS)
    assert NativeInstrumentsScraper.SITEMAP_INDEX in calls
