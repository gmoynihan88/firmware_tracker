import pytest


def _focusrite_category_page() -> str:
    """A category listing: product links one level below, plus links that are not products."""
    return """
    <html><body>
      <nav><a href="/focusrite">Focusrite</a></nav>
      <a href="/focusrite/scarlett-4th-gen">Scarlett 4th Gen</a>
      <a href="/focusrite/scarlett-4th-gen/scarlett-2i2-4th-gen">Scarlett 2i2 4th Gen</a>
      <a href="/focusrite/scarlett-4th-gen/scarlett-solo-4th-gen">Scarlett Solo 4th Gen</a>
      <a href="/focusrite/scarlett-4th-gen/scarlett-2i2-4th-gen/extra">Too deep</a>
      <a href="/other/thing">Unrelated</a>
    </body></html>
    """


def test_focusrite_normalises_names_to_match_existing_rows():
    """The site's spelling differs from the database's; unnormalised it duplicates rows.

    Focusrite writes "Clarett⁺" with a superscript plus (U+207A) and is inconsistent
    about capitalising "gen".
    """
    from src.scrapers.plugins.focusrite import FocusriteScraper

    scraper = FocusriteScraper()

    assert scraper._normalise_name("Clarett⁺ 2Pre") == "Clarett+ 2Pre"
    assert scraper._normalise_name("Scarlett 18i20 3rd gen") == "Scarlett 18i20 3rd Gen"
    assert scraper._normalise_name("Scarlett 8i6 3rd gen") == "Scarlett 8i6 3rd Gen"
    # Already correct names are left alone.
    assert scraper._normalise_name("Scarlett 2i2 4th Gen") == "Scarlett 2i2 4th Gen"
    assert scraper._normalise_name("Vocaster One") == "Vocaster One"


def test_focusrite_detects_a_404_page():
    """Focusrite serves its 404 with full site chrome, so length alone is not enough."""
    from src.scrapers.plugins.focusrite import FocusriteScraper

    scraper = FocusriteScraper()
    filler = "Site navigation and footer boilerplate. " * 80  # comfortably over the floor

    not_found = f"<html><body><h1>Page not found</h1><p>The requested page could not be found.</p>{filler}</body></html>"
    assert scraper._page_rendered(not_found) is False

    assert scraper._page_rendered(f"<html><body>{filler}</body></html>") is True
    assert scraper._page_rendered("<html><body>Loading</body></html>") is False
    assert scraper._page_rendered(None) is False


@pytest.mark.asyncio
async def test_focusrite_discovers_products_from_a_category_listing():
    """Only links exactly one level below the category are products."""
    from src.scrapers.plugins.focusrite import FocusriteScraper

    scraper = FocusriteScraper()

    async def _page(*_args, **_kwargs):
        # Pad so _page_rendered accepts it.
        return _focusrite_category_page() + "<p>" + ("padding text. " * 200) + "</p>"

    scraper.fetch_page_js = _page
    devices = await scraper._products_in_category("scarlett-4th-gen")

    names = sorted(d.name for d in devices)
    assert names == ["Scarlett 2i2 4th Gen", "Scarlett Solo 4th Gen"]
    assert devices[0].firmware_page_url.startswith("https://downloads.focusrite.com/focusrite/")


@pytest.mark.asyncio
async def test_focusrite_reports_no_firmware_without_fetching():
    """Focusrite publishes no per-device version, so this is an empty success.

    It must not fetch: 28 pointless page loads previously consumed ~95s of the 120s
    per-manufacturer budget and timed out the last devices.
    """
    from src.scrapers.plugins.focusrite import FocusriteScraper

    scraper = FocusriteScraper()

    async def _explode(*_args, **_kwargs):
        raise AssertionError("fetch_firmware_versions must not fetch the product page")

    scraper.fetch_page_js = _explode
    result = await scraper.fetch_firmware_versions("Scarlett 2i2 4th Gen", "https://example.invalid")

    assert result.success is True
    assert result.firmware_versions == []
