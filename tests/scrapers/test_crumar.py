def test_crumar_unverified_version_is_labelled():
    """The D9-X value has no public source and must say so."""
    from src.scrapers.plugins.crumar import CrumarScraper

    entry = CrumarScraper.UNVERIFIED_FIRMWARE["D9-X"][0]
    assert entry[2].startswith("Unverified:")
