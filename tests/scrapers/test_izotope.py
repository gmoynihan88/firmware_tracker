import pytest


def _izotope_page() -> str:
    """A release-notes page: dated entries, plus OS and host versions to trip a parser."""
    return """
    <html><body>
      <h1>Ozone 12 Standard Release Notes</h1>
      <p>Version 12.1.0 released December 1, 2025</p>
      <p>Improved Master Assistant.</p>
      <p>Version 12.0.0 released September 2, 2025</p>
      <p>Supported: macOS Ventura (13.7), macOS Sonoma (14.7)</p>
      <p>Hosts: Logic Pro 10.8 - 11, Pro Tools 2024 - 2025, Cubase 14</p>
      <p>Version 11.3.0 released September 9, 2025</p>
      <p>Version 11.2.0 released August 22, 2024</p>
    </body></html>
    """


def test_izotope_ignores_os_and_host_versions():
    """The same pages quote macOS and DAW versions, which are not releases."""
    from src.scrapers.plugins.izotope import IZotopeScraper

    releases = IZotopeScraper()._parse_releases(_izotope_page())
    versions = {fw.version for fw in releases}

    assert versions == {"12.1.0", "12.0.0", "11.3.0", "11.2.0"}
    for noise in ("13.7", "14.7", "10.8", "2024", "14"):
        assert noise not in versions


def test_izotope_orders_by_release_date():
    """iZotope's numbering is not monotonic.

    Insight lists "2.10" from February 2019 next to "2.6.0" from April 2025, so
    comparing the numbers puts a six-year-old build on top.
    """
    from src.scrapers.plugins.izotope import IZotopeScraper

    html = """
    <html><body>
      <p>Version 2.10 released February 26, 2019</p>
      <p>Version 2.6.0 released April 28, 2025</p>
    </body></html>
    """
    releases = IZotopeScraper()._parse_releases(html)

    assert [fw.version for fw in releases] == ["2.6.0", "2.10"]


@pytest.mark.asyncio
async def test_izotope_reports_only_the_matching_major():
    """A newer major is a paid upgrade, not an available update.

    Someone running Ozone 11 should not be told 12.1.0 is available for them.
    """
    from src.scrapers.plugins.izotope import IZotopeScraper

    scraper = IZotopeScraper()

    async def _page(*_args, **_kwargs):
        return _izotope_page()

    scraper.fetch_page_js = _page

    eleven = await scraper.fetch_firmware_versions("Ozone 11", "https://example.invalid")
    assert [fw.version for fw in eleven.firmware_versions] == ["11.3.0", "11.2.0"]

    twelve = await scraper.fetch_firmware_versions("Ozone 12", "https://example.invalid")
    assert [fw.version for fw in twelve.firmware_versions] == ["12.1.0", "12.0.0"]


def test_izotope_resolves_tiered_device_names():
    """Elements and Advanced are separate pages, not separate parsing."""
    from src.scrapers.plugins.izotope import IZotopeScraper

    scraper = IZotopeScraper()

    assert scraper._resolve("Ozone 11") == ("ozone-standard-release-notes", "11")
    assert scraper._resolve("Ozone 11 Elements") == ("ozone-elements-release-notes", "11")
    assert scraper._resolve("RX 12 Advanced") == ("rx-advanced-release-notes", "12")
    assert scraper._resolve("Neutron 5") == ("neutron-release-notes", "5")
    # VocalSynth has no release-notes page, so it must not resolve to a guess.
    assert scraper._resolve("VocalSynth 2") is None


@pytest.mark.asyncio
async def test_izotope_unknown_product_fails_rather_than_returning_empty():
    from src.scrapers.plugins.izotope import IZotopeScraper

    result = await IZotopeScraper().fetch_firmware_versions("Nonexistent 9", "https://example.invalid")

    assert result.success is False
    assert "no izotope release-notes page" in result.error.lower()
