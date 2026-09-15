import pytest


def test_soundforce_parses_both_page_formats():
    """WordPress pages write "V1.11:"; the Notion pages prefix a date."""
    from src.scrapers.plugins.soundforce import SoundForceScraper

    html = """
    <html><body>
      <p>V1.11:</p><p>MacOS updater app download</p>
      <p>V1.11:</p><p>Windows updater</p>
      <p>V1.10:</p><p>MacOS updater app download</p>
      <p>25/11/2025: V1.9:</p><p>Notion-style entry with a date</p>
    </body></html>
    """
    versions = SoundForceScraper()._parse_updates(html)

    # Each version is listed twice, once per platform; they must not double up.
    assert [fw.version for fw in versions] == ["1.11", "1.10", "1.9"]
    assert versions[0].release_date is None          # WordPress entries carry no date
    assert versions[2].release_date.strftime("%Y-%m-%d") == "2025-11-25"


def test_soundforce_orders_versions_numerically():
    """1.11 must outrank 1.9, which string ordering reverses."""
    from src.scrapers.plugins.soundforce import SoundForceScraper

    html = "<html><body><p>V1.9:</p><p>V1.11:</p><p>V1.10:</p></body></html>"
    versions = SoundForceScraper()._parse_updates(html)

    assert [fw.version for fw in versions] == ["1.11", "1.10", "1.9"]


@pytest.mark.asyncio
async def test_soundforce_resolves_update_pages_from_the_support_page():
    """URLs come from the Support page, not from hardcoded WordPress page ids.

    Two of the old ?page_id= values had changed and returned an identical
    1037-character "Page Not Found".
    """
    from src.scrapers.plugins.soundforce import SoundForceScraper

    scraper = SoundForceScraper()
    support = """
    <html><body>
      <a href="https://sound-force.nl/?page_id=5155">SFC-60 V3 updates</a>
      <a href="https://sound-force.nl/?page_id=5145">SFC-5 V2 updates</a>
      <a href="https://sound-force.nl/shop">Webshop</a>
    </body></html>
    """
    fetched = []

    async def _page(url, *_args, **_kwargs):
        fetched.append(url)
        if url == scraper.SUPPORT_URL:
            return support
        return "<html><body><p>V2.7:</p></body></html>"

    scraper.fetch_page_js = _page

    result = await scraper.fetch_firmware_versions("SFC-5", scraper.SUPPORT_URL)
    assert result.success is True
    assert result.firmware_versions[0].version == "2.7"
    # It followed the link the support page gave, not a hardcoded id.
    assert "page_id=5145" in fetched[-1]

    # A product the support page does not link is a failure, not an empty success.
    missing = await scraper.fetch_firmware_versions("SFC-8", scraper.SUPPORT_URL)
    assert missing.success is False


@pytest.mark.asyncio
async def test_soundforce_fetches_the_support_page_once():
    """The index is shared by every device."""
    from src.scrapers.plugins.soundforce import SoundForceScraper

    scraper = SoundForceScraper()
    support_fetches = []

    async def _page(url, *_args, **_kwargs):
        if url == scraper.SUPPORT_URL:
            support_fetches.append(url)
            return '<html><body><a href="/u">SFC-60 V3 updates</a><a href="/u">SFC-5 V2 updates</a></body></html>'
        return "<html><body><p>V1.11:</p></body></html>"

    scraper.fetch_page_js = _page

    for name in ("SFC-60", "SFC-5"):
        assert (await scraper.fetch_firmware_versions(name, scraper.SUPPORT_URL)).success

    assert len(support_fetches) == 1


def test_soundforce_reads_a_date_that_sits_above_the_version():
    """Sound-Force puts the date on its own line, behind a dash, above the version.

    The combined pattern only matched when both shared a line, so seven releases were
    stored with no date at all while the date sat one line up in the same page.
    """
    from src.scrapers.plugins.soundforce import SoundForceScraper

    html = """<p>\u2013 07/10/2024:</p><p>V1.11:</p><p>MacOS updater app download</p>
    <p>V1.11:</p><p>Windows updater</p>
    <p>\u2013 18/07/2022:</p><p>V1.10:</p><p>MacOS updater app download</p>"""

    versions = SoundForceScraper()._parse_updates(html)
    dates = {fw.version: fw.release_date for fw in versions}

    # 07/10/2024 is day/month: the page's other entries (18/07, 13/06) can only be
    # read that way, so this is 7 October rather than 10 July.
    assert dates["1.11"].strftime("%Y-%m-%d") == "2024-10-07"
    assert dates["1.10"].strftime("%Y-%m-%d") == "2022-07-18"
    # One date heads both the macOS and Windows entries, which dedupe to one version.
    assert len(versions) == 2


def test_soundforce_does_not_attach_a_date_to_an_unrelated_version():
    """A version appearing before any date line must stay undated."""
    from src.scrapers.plugins.soundforce import SoundForceScraper

    html = "<p>V2.0:</p><p>early entry</p><p>\u2013 13/06/2022:</p><p>V1.9:</p>"

    dates = {fw.version: fw.release_date for fw in SoundForceScraper()._parse_updates(html)}

    assert dates["2.0"] is None
    assert dates["1.9"].strftime("%Y-%m-%d") == "2022-06-13"
