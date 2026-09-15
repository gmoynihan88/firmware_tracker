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


# The Support page's own markup: current controllers in one paragraph, legacy ones
# under their own heading, update pages on two hosts.
SUPPORT_PAGE = """
<p><a href="https://soundforce.notion.site/SFC-Mini-V4-Firmware-updates-2d78e657f71c" rel="noopener" target="_blank">SFC-Mini V4 updates</a><br/>
<a href="https://sound-force.nl/?page_id=6118">SFC-OB updates</a><br/>
<a href="https://sound-force.nl/?page_id=5155">SFC-60 V3 updates</a><br/>
<a href="https://sound-force.nl/?page_id=5145">SFC-5 V2 updates</a></p>
<p><a href="https://sound-force.nl/shop">Webshop</a></p>
<p><em><strong>Legacy controllers:</strong></em><br/>
<a href="https://sound-force.nl/?page_id=5110" rel="noopener" target="_blank">SFC-Mini V3 updates</a></p>
"""


def _with_pages(scraper, pages):
    fetched = []

    async def _page(url, *_args, **_kwargs):
        fetched.append(url)
        return pages.get(url)

    scraper.fetch_page_js = _page
    return fetched


@pytest.mark.asyncio
async def test_soundforce_lists_every_controller_the_support_page_links():
    """The catalogue is the Support page's update links, not a list kept by hand."""
    from src.scrapers.plugins.soundforce import SoundForceScraper

    scraper = SoundForceScraper()
    _with_pages(scraper, {scraper.SUPPORT_URL: SUPPORT_PAGE.replace(
        "</p>\n<p><a href=\"https://sound-force.nl/shop\">",
        '<br/>\n<a href="https://sound-force.nl/?page_id=7001">SFC-9 updates</a></p>\n<p><a href="https://sound-force.nl/shop">',
    )})

    result = await scraper.fetch_device_list()

    assert result.success is True
    devices = {d.name: d.firmware_page_url for d in result.devices}
    # A controller the page adds is picked up under the page's own name.
    assert devices["SFC-9"] == "https://sound-force.nl/?page_id=7001"
    assert "Webshop" not in devices
    # Legacy controllers are linked under their own heading and still listed.
    assert devices["SFC-Mini"] == "https://sound-force.nl/?page_id=5110"
    # Each device reads the page its link names.
    assert devices["SFC-Mini V4"].startswith("https://soundforce.notion.site/")


@pytest.mark.asyncio
async def test_soundforce_keeps_the_names_the_database_already_has():
    """The page names controllers by revision; three were catalogued without one.

    Only those three are renamed. SFC-Mini V4 is a different controller from the
    SFC-Mini and must keep its V4, so this is not a rule that strips revisions.
    """
    from src.scrapers.plugins.soundforce import SoundForceScraper

    scraper = SoundForceScraper()
    _with_pages(scraper, {scraper.SUPPORT_URL: SUPPORT_PAGE})

    names = [d.name for d in (await scraper.fetch_device_list()).devices]

    assert names == ["SFC-Mini V4", "SFC-OB", "SFC-60", "SFC-5", "SFC-Mini"]


@pytest.mark.asyncio
async def test_soundforce_fails_when_the_support_page_links_nothing():
    from src.scrapers.plugins.soundforce import SoundForceScraper

    unreachable = SoundForceScraper()
    _with_pages(unreachable, {})
    assert (await unreachable.fetch_device_list()).success is False

    rearranged = SoundForceScraper()
    _with_pages(rearranged, {rearranged.SUPPORT_URL: '<p><a href="/shop">Webshop</a></p>'})
    assert (await rearranged.fetch_device_list()).success is False


@pytest.mark.asyncio
async def test_soundforce_reads_the_update_page_it_was_given():
    from src.scrapers.plugins.soundforce import SoundForceScraper

    scraper = SoundForceScraper()
    page = "https://sound-force.nl/?page_id=5145"
    fetched = _with_pages(scraper, {page: "<p>V2.7:</p>", "https://sound-force.nl/?page_id=1": "<p>no releases</p>"})

    result = await scraper.fetch_firmware_versions("SFC-5", page)
    assert result.success is True
    assert result.firmware_versions[0].version == "2.7"
    assert fetched == [page]

    # A page that loads with no release on it is a failure, not an empty success.
    empty = await scraper.fetch_firmware_versions("SFC-5", "https://sound-force.nl/?page_id=1")
    assert empty.success is False


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
