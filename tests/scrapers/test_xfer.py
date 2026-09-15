import pytest

from tests.support import _stub_fetch


XFER_HOME = ('<a href="/products/serum-2">Serum 2</a><a href="/products/nerve">Nerve</a>'
             '<a href="/products/serum-2">Buy</a><a href="/preset_packs/techno-2">Techno 2</a>')


def _xfer_product(title, *slugs):
    """A product page: its title, the site nav, and demo links named after builds."""
    return (f"<title>{title}</title>" + XFER_HOME
            + '<a href="/shopping_cart/add?product_id=135">Buy Now $249.00 USD</a>'
            + "".join(f'<a href="/product_downloads/{slug}/demo">Demo</a>' for slug in slugs))


def test_xfer_reads_the_version_through_the_product_number_and_the_uuid():
    """serum-2-1-5 is Serum 2 at 2.1.5, not 1.5; a UUID's all-digit groups are not a version."""
    from src.scrapers.plugins.xfer import XferScraper

    page = _xfer_product(
        "Serum 2: Advanced Hybrid Synthesizer",
        "serum-2-1-5-for-macos-80e73b6e-0018-454e-8a42-12bbdf5aaa31",
        "serum-2-1-5-for-windows-bfbeec48-5121-4035-9c8f-9c7cf2ea4bee",
    )
    # No major in the name to catch it, so only removing the UUID keeps 0018-4540 out.
    unversioned = _xfer_product("LFO Tool: Powerful LFO Shaping",
                                "lfo-tool-demo-osx-80e73b6e-0018-4540-8a42-12bbdf5aaa31")

    assert XferScraper()._parse_product(page, "serum-2") == ("Serum 2", "2.1.5")
    assert XferScraper()._parse_product(unversioned, "lfo-tool") == ("LFO Tool", None)


def test_xfer_keeps_the_newest_platform_build_compared_numerically():
    """Cthulhu is 1.11 on Windows and 1.1 on macOS. As text, 1.9 would beat 1.11."""
    from src.scrapers.plugins.xfer import XferScraper

    page = _xfer_product("Cthulhu: The Chord and Arp Monster",
                         "cthulhu-demo-1-11-windows", "cthulhu-demo-1-1-osx")

    behind = _xfer_product("Cthulhu: The Chord and Arp Monster",
                           "cthulhu-demo-1-9-osx", "cthulhu-demo-1-11-windows")

    assert XferScraper()._parse_product(page, "cthulhu") == ("Cthulhu", "1.11")
    assert XferScraper()._parse_product(behind, "cthulhu") == ("Cthulhu", "1.11")


def test_xfer_refuses_a_version_off_the_products_major_and_other_products_demos():
    from src.scrapers.plugins.xfer import XferScraper

    page = _xfer_product("Serum 2: Advanced Hybrid Synthesizer",
                         "serum-2-demo-1-5-osx", "nerve-demo-1-2-3-windows")

    assert XferScraper()._parse_product(page, "serum-2") == ("Serum 2", None)


@pytest.mark.asyncio
async def test_xfer_discovers_products_from_the_home_page():
    from src.scrapers.plugins.xfer import XferScraper as X

    scraper = X()
    asked = _stub_fetch(scraper, {
        X.HOME_URL: XFER_HOME,
        "https://xferrecords.com/products/serum-2": _xfer_product(
            "Serum 2: Advanced Hybrid Synthesizer", "serum-2-1-5-for-macos-80e73b6e-0018-454e-8a42-12bbdf5aaa31"),
        "https://xferrecords.com/products/nerve": _xfer_product(
            "Nerve: Powerful beat manipulation", "nerve-demo-1-1-osx", "nerve-demo-1-2-3-windows"),
    })

    devices = (await scraper.fetch_device_list()).devices
    versions = {d.name: [fw.version for fw in (await scraper.fetch_firmware_versions(d.name, d.firmware_page_url)).firmware_versions]
                for d in devices}

    assert versions == {"Serum 2": ["2.1.5"], "Nerve": ["1.2.3"]}
    assert len(asked) == 3  # home and two products, once each


@pytest.mark.asyncio
async def test_xfer_fails_the_listing_when_a_product_page_does_not_load():
    """Rather than list the rest and leave that product silently missing."""
    from src.scrapers.plugins.xfer import XferScraper as X

    scraper = X()
    _stub_fetch(scraper, {
        X.HOME_URL: XFER_HOME,
        "https://xferrecords.com/products/serum-2": _xfer_product(
            "Serum 2: Advanced Hybrid Synthesizer", "serum-2-1-5-for-macos-80e73b6e-0018-454e-8a42-12bbdf5aaa31"),
    })

    assert (await scraper.fetch_device_list()).success is False
