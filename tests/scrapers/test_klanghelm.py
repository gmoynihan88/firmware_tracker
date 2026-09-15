import pytest

from tests.support import _stub_fetch


def _kh_product(title, body):
    return f"<html><head><title>{title}</title></head><body>{body}</body></html>"


KH_FREE = _kh_product(
    "DC1A",
    "<p>DC1A3 is the third generation. Requires macOS 10.13 or newer.</p>"
    "<p>Download DC1A: (version 3.5.0)</p>"
    '<a href="https://klanghelm.com/free/DC1A3dl.php?id=1">DC1A3 - Windows Installer</a>'
    '<a href="../../docs/DC1A3-manual.pdf">Download the manual (pdf)</a>',
)


KH_PAID = _kh_product(
    "DC8C",
    "<p>DC8C 3 brings four operational modes. Requires macOS 10.13 or newer.</p>"
    '<a href="../../docs/DC8C3-manual.pdf">Download the manual</a>'
    '<a href="https://secure.2checkout.com/checkout/buy?prod=C20FAD0766">Buy</a>',
)


KH_FALLBACK = _kh_product("Klanghelm Home", '<a href="../products/DC1A">DC1A</a>')


def test_klanghelm_reads_only_the_version_a_page_states():
    """Not the generation in "DC1A3", nor macOS 10.13."""
    from src.scrapers.plugins.klanghelm import KlanghelmScraper

    assert KlanghelmScraper()._parse_product(KH_FREE) == ("DC1A", "3.5.0")
    assert KlanghelmScraper()._parse_product(KH_PAID) == ("DC8C", None)


def test_klanghelm_knows_the_home_page_fallback_is_not_a_product():
    """Any unknown path returns the home page with a 200."""
    from src.scrapers.plugins.klanghelm import KlanghelmScraper

    assert KlanghelmScraper()._parse_product(KH_FALLBACK) is None


def _kh_site():
    from src.scrapers.plugins.klanghelm import KlanghelmScraper as KH

    base = "https://klanghelm.com/contents/products"
    return {
        KH.HOME_URL: (
            '<a href="../products/DC1A">DC1A</a><a href="../products/DC1A.html">FREE</a>'
            '<a href="../products/DC8C">DC8C</a>'
            '<a href="https://secure.2checkout.com/checkout/buy?prod=C20FAD0766">Buy</a>'
        ),
        f"{base}/DC1A.html": KH_FREE,
        f"{base}/DC8C.html": KH_PAID,
    }


@pytest.mark.asyncio
async def test_klanghelm_versions_free_plugins_and_flags_paid_ones_not_published():
    from src.scrapers.plugins.klanghelm import KlanghelmScraper as KH

    scraper = KH()
    asked = _stub_fetch(scraper, _kh_site())

    devices = (await scraper.fetch_device_list()).devices
    versions = {
        d.name: [fw.version for fw in (await scraper.fetch_firmware_versions(d.name, d.firmware_page_url)).firmware_versions]
        for d in devices
    }

    assert [(d.name, d.firmware_availability) for d in devices] == [("DC1A", None), ("DC8C", "not_published")]
    assert versions == {"DC1A": ["3.5.0"], "DC8C": []}
    assert len(asked) == 3  # home, and each product once despite its two links


@pytest.mark.asyncio
async def test_klanghelm_fails_the_listing_when_a_product_returns_the_home_page():
    """A moved product would otherwise be catalogued as one that publishes nothing."""
    from src.scrapers.plugins.klanghelm import KlanghelmScraper as KH

    scraper = KH()
    site = _kh_site()
    site["https://klanghelm.com/contents/products/DC8C.html"] = KH_FALLBACK
    _stub_fetch(scraper, site)

    assert (await scraper.fetch_device_list()).success is False
