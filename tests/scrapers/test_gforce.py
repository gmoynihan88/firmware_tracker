import pytest


def _gforce_releases_page() -> str:
    """The Updates And Releases page: one div.update-release-item per release."""
    return """
    <html><body>
      <div class="update-release-item">
        <span>06/30/2026</span>
        <div class="text-content">
          <a>Oberheim OB-E&#174;</a>
          <div class="description">
            <h3><strong>v2.5.1</strong></h3>
            <ul><li>Fixed voice allocation.</li></ul>
            <a class="product-link" href="/product/ob-e/">View Oberheim OB-E&#174;</a>
          </div>
        </div>
      </div>
      <div class="update-release-item">
        <span>04/03/2023</span>
        <div class="text-content">
          <a>Oberheim OB-E&#174;</a>
          <div class="description">
            <h3><strong>v2.0</strong></h3>
            <ul><li>Earlier release.</li></ul>
            <a class="product-link" href="/product/ob-e/">View Oberheim OB-E&#174;</a>
          </div>
        </div>
      </div>
      <div class="update-release-item">
        <span>02/11/2026</span>
        <div class="text-content">
          <a>VSM IV</a>
          <div class="description">
            <h3><strong>v1.1</strong></h3>
            <ul><li>Fixed stereo sample playback.</li></ul>
            <a class="product-link" href="/product/vsm-iv/">View VSM IV</a>
          </div>
        </div>
      </div>
    </body></html>
    """


def test_gforce_strips_trademark_symbols_from_product_names():
    """GForce writes "Oberheim OB-E®"; the database row is "Oberheim OB-E".

    Without normalising, a scrape creates a second row and orphans the first.
    """
    from src.scrapers.plugins.gforce import GForceScraper

    releases = GForceScraper()._parse_releases(_gforce_releases_page())

    assert "Oberheim OB-E" in releases
    assert not any("®" in name for name in releases)


def test_gforce_orders_releases_and_keeps_dates():
    from src.scrapers.plugins.gforce import GForceScraper

    releases = GForceScraper()._parse_releases(_gforce_releases_page())

    obe = releases["Oberheim OB-E"]
    assert [fw.version for fw in obe] == ["2.5.1", "2.0"]
    assert obe[0].release_date.strftime("%Y-%m-%d") == "2026-06-30"
    assert "voice allocation" in obe[0].changelog
    assert obe[0].download_url.endswith("/product/ob-e/")


@pytest.mark.asyncio
async def test_gforce_resolves_a_renamed_product():
    """Virtual String Machine is now listed as VSM IV."""
    from src.scrapers.plugins.gforce import GForceScraper

    scraper = GForceScraper()

    async def _page(*_args, **_kwargs):
        return _gforce_releases_page()

    scraper.fetch_page_js = _page

    renamed = await scraper.fetch_firmware_versions("Virtual String Machine", scraper.RELEASES_URL)
    assert renamed.success is True
    assert renamed.firmware_versions[0].version == "1.1"


@pytest.mark.asyncio
async def test_gforce_lists_only_products_with_releases_on_the_page():
    """M-Tron Pro used to be listed with no releases, so its row would not look broken.

    Its product page now redirects to M-Tron Pro IV, so it is not listed at all -- and
    a name that is not on the page fails rather than reporting an empty history.
    """
    from src.scrapers.plugins.gforce import GForceScraper

    scraper = GForceScraper()

    async def _page(*_args, **_kwargs):
        return _gforce_releases_page()

    scraper.fetch_page_js = _page

    listing = await scraper.fetch_device_list()
    assert sorted(d.name for d in listing.devices) == ["Oberheim OB-E", "VSM IV"]

    for name in ("M-Tron Pro", "Not A Product"):
        assert (await scraper.fetch_firmware_versions(name, scraper.RELEASES_URL)).success is False
