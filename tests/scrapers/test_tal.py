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


def _card(slug, name, description=""):
    """A product card as /products renders it."""
    return f"""
    <div class="well col-sm-2 productbox">
      <a class="img-badge" href="/products/{slug}">
        <img alt="Details" class="img-fluid productboxImage" src="../../images/products/thumb_{slug}.png"/>
        <span class="badge badge-sale"></span>
      </a>
      <div class="productbuttonspace">
        <a href="/products/{slug}"><h6>{name}</h6></a>
        <button class="btn btn-primary btn-large productbutton" producttocheckout="{slug}">ADD</button>
      </div>
      <div class="productdescription">{description}</div>
    </div>"""


TAL_INDEX = "".join([
    _card("tal-j-8x", "TAL-J-8X", "JX 8P Emulation"),
    # A bundle's card links to its first member's page. Placed ahead of that member
    # here, so the bundle's name would claim the page if bundles were not skipped.
    _card("tal-u-no-lx", "Analog Bundle", "TAL-U-NO-LX , TAL-J-8 and TAL-BassLine-101"),
    _card("tal-u-no-lx", "TAL-U-NO-LX", "Juno 60 Emulation"),
    _card("tal-mod", "TAL-Mod", "Semi-Modular Synthesizer"),
    _card("tal-dub", "TAL-Dub's", "TAL-Dub's"),
])

TAL_PAGES = {
    "https://tal-software.com/products": TAL_INDEX,
    "https://tal-software.com/products/tal-j-8x": "<div>v1.0.9</div><div>Version 1.0.8 / 02.03.2026</div><div>Fixes.</div>",
    "https://tal-software.com/products/tal-u-no-lx": _tal_page(),
    "https://tal-software.com/products/tal-mod": "<div>v 1.9.8</div>",
    # A legacy freebie: the page renders its downloads, and states no version anywhere.
    "https://tal-software.com/products/tal-dub": (
        "<div>TAL-Dub</div><div>Downloads</div><div>archive</div>"
        "<div>Windows (32 bit VST): TAL-Dub.zip</div><div>Requirements:</div>"
    ),
}

# What the app serves before it has rendered a product: navigation and nothing else.
TAL_SHELL = (
    "<div>TAL Software</div><div>You need to enable JavaScript to run this app.</div>"
    "<div>NEWS</div><div>PLUGINS</div><div>SUPPORT</div>"
)


def _tal_scraper(pages):
    from src.scrapers.plugins.tal import TALScraper

    scraper = TALScraper()
    rendered = []

    async def _page(url, *_args, **_kwargs):
        rendered.append(url)
        return pages.get(url)

    scraper.fetch_page_js = _page
    return scraper, rendered


@pytest.mark.asyncio
async def test_tal_lists_the_plugins_on_the_products_page():
    """The catalogue is the index's cards, not a hand-kept list of nine."""
    scraper, _ = _tal_scraper(TAL_PAGES)

    result = await scraper.fetch_device_list()

    assert result.success is True
    devices = {d.name: d.firmware_page_url for d in result.devices}
    assert devices["TAL-J-8X"] == "https://tal-software.com/products/tal-j-8x"
    assert all(d.category == "vst_plugin" for d in result.devices)


@pytest.mark.asyncio
async def test_tal_keeps_the_names_the_database_has():
    scraper, _ = _tal_scraper(TAL_PAGES)

    names = [d.name for d in (await scraper.fetch_device_list()).devices]

    assert "TAL-U-NO-LX-V2" in names and "TAL-MOD" in names
    assert "TAL-U-NO-LX" not in names and "TAL-Mod" not in names


@pytest.mark.asyncio
async def test_tal_skips_bundles_and_plugins_with_no_version():
    """A bundle card links to a member's page; a legacy freebie states no version."""
    scraper, _ = _tal_scraper(TAL_PAGES)

    names = [d.name for d in (await scraper.fetch_device_list()).devices]

    assert names == ["TAL-J-8X", "TAL-U-NO-LX-V2", "TAL-MOD"]


@pytest.mark.asyncio
async def test_tal_renders_each_page_once_per_scrape():
    """Rendering is TAL's whole cost; the listing's pages are reused for versions."""
    scraper, rendered = _tal_scraper(TAL_PAGES)

    listing = await scraper.fetch_device_list()
    for device in listing.devices:
        result = await scraper.fetch_firmware_versions(device.name, device.firmware_page_url)
        assert result.success is True, device.name

    assert sorted(rendered) == sorted(TAL_PAGES)
    j8x = await scraper.fetch_firmware_versions("TAL-J-8X", "https://tal-software.com/products/tal-j-8x")
    assert [fw.version for fw in j8x.firmware_versions] == ["1.0.9", "1.0.8"]


@pytest.mark.asyncio
async def test_tal_fails_the_listing_when_a_page_does_not_render():
    pages = dict(TAL_PAGES)
    del pages["https://tal-software.com/products/tal-mod"]
    scraper, _ = _tal_scraper(pages)
    assert (await scraper.fetch_device_list()).success is False

    no_index, _ = _tal_scraper({})
    assert (await no_index.fetch_device_list()).success is False


@pytest.mark.asyncio
async def test_tal_still_reads_a_row_the_index_no_longer_lists():
    """A plug-in TAL drops from the index keeps being read from its stored page."""
    scraper, _ = _tal_scraper(TAL_PAGES)
    await scraper.fetch_device_list()

    url = "https://tal-software.com/products/tal-sampler"
    scraper_pages = dict(TAL_PAGES, **{url: "<div>v4.8.6</div>"})

    async def _page(u, *_a, **_k):
        return scraper_pages.get(u)

    scraper.fetch_page_js = _page
    result = await scraper.fetch_firmware_versions("TAL-Sampler", url)

    assert result.success is True
    assert result.firmware_versions[0].version == "4.8.6"


@pytest.mark.asyncio
async def test_tal_fails_the_listing_when_a_product_page_renders_without_content():
    """TAL-Drum vanished from a live listing: its page stated no version that time.

    Skipping every versionless page would read that as a legacy freebie. Only a page
    that shows its downloads and has no change log is one.
    """
    shell = _tal_scraper(dict(TAL_PAGES, **{"https://tal-software.com/products/tal-mod": TAL_SHELL}))[0]
    assert (await shell.fetch_device_list()).success is False

    empty_log = dict(TAL_PAGES, **{
        "https://tal-software.com/products/tal-mod":
            '<div>Downloads</div><div id="changelog"><div>CHANGE LOG</div></div>',
    })
    assert (await _tal_scraper(empty_log)[0].fetch_device_list()).success is False
