import pytest


def _tal_page() -> str:
    """A TAL product page: shipping version in the download block, dated history."""
    return """
    <html><body>
      <h1>TAL-U-NO-LX</h1>
      <div>Downloads</div>
      <div>v5.1.3</div>
      <div>VST</div>
      <div>Version 5.1.2 / 03.11.2025</div>
      <div>MPE pitch not stay in note release fixed.</div>
      <div>Version 5.1.1 / 17.09.2025</div>
      <div>More MPE options. Framework update.</div>
      <div>Version 4.9.5 / 05.11.2024</div>
      <div>More flexible serial key verification.</div>
    </body></html>
    """


def test_tal_pairs_each_version_with_its_own_date():
    """Each release keeps its own date rather than inheriting a neighbour's.

    The previous parser took the first version and the first date out of the same
    block, so 4.9.5 was recorded with 5.1.2's date of 2025-11-03.
    """
    from src.scrapers.plugins.tal import TALScraper

    parsed = {fw.version: fw for fw in TALScraper()._parse_changelog(_tal_page())}

    assert parsed["4.9.5"].release_date.strftime("%Y-%m-%d") == "2024-11-05"
    assert parsed["5.1.2"].release_date.strftime("%Y-%m-%d") == "2025-11-03"
    assert "serial key" in parsed["4.9.5"].changelog


def test_tal_captures_shipping_version_absent_from_changelog():
    """5.1.3 ships but has no changelog entry, so the download block is the source."""
    from src.scrapers.plugins.tal import TALScraper

    versions = TALScraper()._parse_changelog(_tal_page())

    assert versions[0].version == "5.1.3"
    assert versions[0].release_date is None  # not published, so not invented
    assert len(versions) == 4


def test_tal_download_version_tolerates_spacing():
    """Product pages differ: "v5.1.3" on one, "v 1.9.8" on another."""
    from src.scrapers.plugins.tal import TALScraper

    scraper = TALScraper()
    assert scraper.DOWNLOAD_VERSION.match("v5.1.3").group(1) == "5.1.3"
    assert scraper.DOWNLOAD_VERSION.match("v 1.9.8").group(1) == "1.9.8"


@pytest.mark.asyncio
async def test_tal_merges_known_history_when_page_trims_it():
    """Entries dropped from the page survive via KNOWN_FIRMWARE, without overriding it."""
    from src.scrapers.plugins.tal import TALScraper

    scraper = TALScraper()

    async def _page(*_args, **_kwargs):
        return _tal_page()

    scraper.fetch_page_js = _page
    result = await scraper.fetch_firmware_versions("TAL-U-NO-LX-V2", "https://example.invalid")

    versions = [fw.version for fw in result.firmware_versions]
    assert result.success is True
    # Live parse leads, so the shipping version stays first.
    assert versions[0] == "5.1.3"
    # An old release only present in KNOWN_FIRMWARE is still carried.
    assert "4.5.0" in versions
    # No duplicates from the merge.
    assert len(versions) == len(set(versions))
