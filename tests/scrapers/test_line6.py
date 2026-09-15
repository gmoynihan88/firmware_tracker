import pytest


def _line6_firmware_page() -> str:
    """The firmware listing: sidebar holds version, date and compatible products.

    The description deliberately quotes a version in prose, which is how the real
    page reads and what a free-text scan would wrongly pick up as a release.
    """
    return """
    <html><body>
      <div class="release-details">
        <div class="sidebar">
          <b>Version 3.80.0</b><br><b>Released 11/19/24</b><br><br>
          Works with:<br><b>Helix</b><br><b>HX Stomp</b>
        </div>
        <div class="description">Adds new cabs. 3.50 renamed the Mono subcategory.</div>
      </div>
      <div class="release-details">
        <div class="sidebar">
          <b>Version 3.15.0</b><br><b>Released 2/8/22</b><br><br>
          Works with:<br><b>Helix</b>
        </div>
        <div class="description">Earlier release.</div>
      </div>
      <div class="release-details">
        <div class="sidebar">
          <b>Version 2.06.0</b><br><b>Released 7/16/24</b><br><br>
          Works with:<br><b>Relay G10TII Transmitter</b>
        </div>
        <div class="description">Wireless transmitter update.</div>
      </div>
    </body></html>
    """


def test_line6_parses_products_from_the_sidebar_only():
    """One release can apply to several products, and descriptions quote versions.

    Scanning the description text would invent a 3.50 release that this page never
    lists as its own entry.
    """
    from src.scrapers.plugins.line6 import Line6Scraper

    catalogue = Line6Scraper()._parse_catalogue(_line6_firmware_page())

    # Note the ordering: "HX Stomp" sorts before "Helix", uppercase X preceding
    # lowercase e.
    assert sorted(catalogue) == ["HX Stomp", "Helix", "Relay G10TII Transmitter"]
    # Helix appears in two entries; HX Stomp only shares the first.
    assert [fw.version for fw in catalogue["Helix"]] == ["3.80.0", "3.15.0"]
    assert [fw.version for fw in catalogue["HX Stomp"]] == ["3.80.0"]
    assert catalogue["Helix"][0].release_date.strftime("%Y-%m-%d") == "2024-11-19"


def test_line6_orders_releases_newest_first_numerically():
    """3.15.0 must not sort above 3.80.0, as string ordering would have it."""
    from src.scrapers.plugins.line6 import Line6Scraper

    catalogue = Line6Scraper()._parse_catalogue(_line6_firmware_page())
    assert catalogue["Helix"][0].version == "3.80.0"


@pytest.mark.asyncio
async def test_line6_fetches_the_listing_once_for_every_device():
    """One page carries all products; fetching it per device wastes the budget."""
    from src.scrapers.plugins.line6 import Line6Scraper

    scraper = Line6Scraper()
    calls = []

    async def _page(*_args, **_kwargs):
        calls.append(1)
        return _line6_firmware_page()

    scraper.fetch_page_js = _page

    for name in ("Helix", "HX Stomp", "Relay G10II"):
        result = await scraper.fetch_firmware_versions(name, scraper.FIRMWARE_URL)
        assert result.success is True, name

    assert len(calls) == 1, f"expected one fetch, made {len(calls)}"


@pytest.mark.asyncio
async def test_line6_maps_device_names_to_their_release_names():
    """The G10II ships firmware as the G10TII transmitter, under a different name."""
    from src.scrapers.plugins.line6 import Line6Scraper

    scraper = Line6Scraper()

    async def _page(*_args, **_kwargs):
        return _line6_firmware_page()

    scraper.fetch_page_js = _page

    mapped = await scraper.fetch_firmware_versions("Relay G10II", scraper.FIRMWARE_URL)
    assert mapped.success is True
    assert mapped.firmware_versions[0].version == "2.06.0"

    # A product genuinely absent from the listing is a failure, not an empty success.
    missing = await scraper.fetch_firmware_versions("Nonexistent Pedal", scraper.FIRMWARE_URL)
    assert missing.success is False
