import pytest


def test_ni_parses_version_from_thread_title():
    """The current version is read out of the update thread's title."""
    from src.scrapers.plugins.native_instruments import NativeInstrumentsScraper

    scraper = NativeInstrumentsScraper()
    cases = [
        ("Official update status - Kontakt (current version: 8.13.0) - Community", "Kontakt", "8.13.0"),
        # Absynth's thread omits the colon; Guitar Rig's slug says 6 but its title says 7.
        ("Official update status - Absynth 6 (current version 6.1) - Community", "Absynth 6", "6.1"),
        ("Official update status - Guitar Rig 7 (current version: 7.0.2) - Community", "Guitar Rig 7", "7.0.2"),
    ]
    for title, product, version in cases:
        match = scraper.TITLE_VERSION.search(title)
        assert match, title
        assert match.group("product").strip() == product
        assert match.group("version").strip() == version


def test_ni_every_product_has_a_version_source():
    """No product may fall through to 'no source configured'."""
    from src.scrapers.plugins.native_instruments import NativeInstrumentsScraper as NI

    names = {name for name, _c, _u in NI.KNOWN_PRODUCTS}
    covered = set(NI.UPDATE_THREADS) | set(NI.SUPERSEDED_VERSIONS) | set(NI.UNVERIFIED_VERSIONS)
    assert names == covered


@pytest.mark.asyncio
async def test_ni_static_versions_are_labelled():
    """Static values carry their provenance so they are not mistaken for a lookup."""
    from src.scrapers.plugins.native_instruments import NativeInstrumentsScraper

    scraper = NativeInstrumentsScraper()

    superseded = await scraper.fetch_firmware_versions("Kontakt 7", "")
    assert superseded.success is True
    assert "Superseded" in superseded.firmware_versions[0].changelog

    unverified = await scraper.fetch_firmware_versions("Raum", "")
    assert unverified.success is True
    assert "Unverified" in unverified.firmware_versions[0].changelog

    unknown = await scraper.fetch_firmware_versions("Nonexistent Plugin", "")
    assert unknown.success is False
