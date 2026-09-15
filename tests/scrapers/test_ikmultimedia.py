def test_ikmultimedia_does_not_use_kvr_as_a_source():
    """KVR only exposes reviewer versions now, so it must not be consulted."""
    from src.scrapers.plugins.ikmultimedia import IKMultimediaScraper

    sources = IKMultimediaScraper()._get_sources_for_product("some-slug", "some.bundle")
    assert [s.name for s in sources] == ["MacUpdater"]
