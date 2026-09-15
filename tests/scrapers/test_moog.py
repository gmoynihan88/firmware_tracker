import pytest


def _moog_update_page() -> str:
    """A Moog software update page: download blurb plus a Change Log."""
    return """
    <html><body>
      <div>
        <span>macOS All Formats v1.2.0</span>
        <span>Windows All Formats v1.2.0</span>
      </div>
      <div>
        <h2>Change Log</h2>
        <p class="sub-header">1.2.0</p>
        <p>Added Apple Pencil support on iOS.</p>
        <p>Performance improvements to internal DSP.</p>
        <p class="sub-header">1.1.0</p>
        <p>Fix for envelope CV not working correctly anymore in v1.1.0.</p>
        <p class="sub-header">1.0.0</p>
        <p>Initial release.</p>
      </div>
    </body></html>
    """


def test_moog_reads_the_whole_changelog_not_just_the_download():
    """The old parser took only the download blurb, losing the history and its notes."""
    from src.scrapers.plugins.moog import MoogScraper

    versions = MoogScraper()._parse_software_update_page(_moog_update_page())

    assert [fw.version for fw in versions] == ["1.2.0", "1.1.0", "1.0.0"]
    assert "Apple Pencil" in versions[0].changelog
    # Notes stop at the next version rather than swallowing the rest of the log.
    assert "envelope CV" not in versions[0].changelog


def test_moog_keeps_a_shipping_build_absent_from_the_changelog():
    """The download blurb can name a build the Change Log does not list."""
    from src.scrapers.plugins.moog import MoogScraper

    html = _moog_update_page().replace("All Formats v1.2.0", "All Formats v1.3.0")
    versions = MoogScraper()._parse_software_update_page(html)

    assert versions[0].version == "1.3.0"
    assert "1.2.0" in [fw.version for fw in versions]


@pytest.mark.asyncio
async def test_moog_products_without_a_published_version():
    """Three products are App Store apps whose Moog pages 404.

    Every software-update slug except mariana returns the same generic shell -- even
    invented ones -- so there is nothing to read rather than something broken.
    """
    from src.scrapers.plugins.moog import MoogScraper

    scraper = MoogScraper()

    async def _explode(*_args, **_kwargs):
        raise AssertionError("must not fetch for a product with no published version")

    scraper.fetch_page = _explode

    for name in ("Animoog Z", "Moog Model 15", "Minimoog Model D App"):
        result = await scraper.fetch_firmware_versions(name, "https://example.invalid")
        assert result.success is True, name
        assert result.firmware_versions == []


@pytest.mark.asyncio
async def test_moog_reports_the_generic_shell_as_a_failure():
    """A page with no version at all is a failure, not an empty success."""
    from src.scrapers.plugins.moog import MoogScraper

    scraper = MoogScraper()

    async def _shell(*_args, **_kwargs):
        return "<html><body><p>Moog Music</p><p>Download</p></body></html>"

    scraper.fetch_page = _shell
    result = await scraper.fetch_firmware_versions("Mariana", "https://example.invalid")

    assert result.success is False
    assert "shell" in result.error
