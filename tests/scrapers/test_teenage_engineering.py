import pytest


def _te_product_page() -> str:
    """Both layouts on one page, plus changelog prose that mentions versions."""
    return """
    <div class="box bxl"><div class="txt"><span>1.1.33</span></div>
      <div class="txt"><span>2026.09.02</span></div>
      <div class="txt"><span>click to download</span></div></div>
    <div><span>2.5</span></div>
    <div><span>2026.06.24</span></div>
    <div><span>champions update - full release notes, see OS 2.0.2 and support for 2.0</span></div>
    """


def test_te_pairs_a_version_with_the_date_below_it():
    from src.scrapers.plugins.teenage_engineering import TeenageEngineeringScraper as TE

    versions = TE()._parse_product(_te_product_page())

    assert [(fw.version, fw.release_date.strftime("%Y-%m-%d")) for fw in versions] == [
        ("2.5", "2026-06-24"),
        ("1.1.33", "2026-09-02"),
    ]


def test_te_ignores_versions_mentioned_in_the_changelog():
    """"OS 2.0.2" and "support for 2.0" are prose, not releases.

    Both halves must be whole lines: a version line followed by a date line. A search
    would take either of these.
    """
    from src.scrapers.plugins.teenage_engineering import TeenageEngineeringScraper as TE

    found = {fw.version for fw in TE()._parse_product(_te_product_page())}

    assert "2.0.2" not in found
    assert found == {"1.1.33", "2.5"}


def test_te_converts_the_en_dash_in_product_names():
    """The site writes OP–XY with U+2013, which nobody types.

    Left alone the scrape creates a second row beside a user's "OP-XY" and orphans
    the one their device is attached to.
    """
    from src.scrapers.plugins.teenage_engineering import TeenageEngineeringScraper as TE

    assert TE()._normalise_name("OP–XY") == "OP-XY"
    assert TE()._normalise_name("EP–133") == "EP-133"
    assert TE()._normalise_name("TP–7") == "TP-7"


def test_te_leaves_out_pages_that_are_not_a_products_os():
    """Pocket Operators take no firmware; sound packs and the ASIO driver are not
    instruments; the oplab module's markup splits its version across elements."""
    from src.scrapers.plugins.teenage_engineering import TeenageEngineeringScraper as TE

    index = """
    <a class="abox" href="/downloads/op-xy">OP–XY|OS|1.1.33</a>
    <a href="/downloads/po-32">PO–32</a>
    <a href="/downloads/op-xy/sound-packs">sound packs</a>
    <a href="/downloads/usb-asio">usb asio</a>
    <a href="/downloads/op-z/oplab-module">oplab module</a>
    """

    slugs = [slug for slug, _name in TE()._index_products(index)]

    assert slugs == ["op-xy"]


def _te_scraper(pages):
    from src.scrapers.plugins.teenage_engineering import TeenageEngineeringScraper as TE

    scraper = TE()
    asked = []

    async def fake_fetch(url, **kwargs):
        asked.append(url)
        return pages.get(url)

    scraper.fetch_page = fake_fetch
    return scraper, asked


@pytest.mark.asyncio
async def test_te_device_list_uses_the_index_names_and_slugs():
    """Names come from the index, URLs from the slug, and the index is read once."""
    from src.scrapers.plugins.teenage_engineering import TeenageEngineeringScraper as TE

    pages = {TE.INDEX_URL: """
        <a class="abox" href="/downloads/op-xy">OP–XY|OS|1.1.33|go to downloads</a>
        <a class="abox" href="/downloads/tx-6">TX–6|OS|1.3.3|go to downloads</a>
    """}
    scraper, asked = _te_scraper(pages)

    devices = await scraper.fetch_device_list()
    await scraper.fetch_device_list()

    assert [d.name for d in devices.devices] == ["OP-XY", "TX-6"]
    assert devices.devices[0].firmware_page_url.endswith("/downloads/op-xy")
    assert asked.count(TE.INDEX_URL) == 1, "re-read the index"


@pytest.mark.asyncio
async def test_te_names_a_product_the_index_does_not_spell_out():
    """op-1 is linked but has no version row, so it has no display text there."""
    from src.scrapers.plugins.teenage_engineering import TeenageEngineeringScraper as TE

    scraper, _ = _te_scraper({TE.INDEX_URL: '<a href="/downloads/op-1">.</a>'})
    devices = await scraper.fetch_device_list()

    assert [d.name for d in devices.devices] == ["OP-1"]


@pytest.mark.asyncio
async def test_te_fails_loudly_when_the_index_is_unreachable():
    from src.scrapers.plugins.teenage_engineering import TeenageEngineeringScraper as TE

    scraper, _ = _te_scraper({})
    result = await scraper.fetch_device_list()

    assert result.success is False
    assert TE.INDEX_URL in result.error


@pytest.mark.asyncio
async def test_te_reports_an_undated_current_version():
    """OP-1 is discontinued: one version, no history, no date.

    Reporting nothing would be a parse failure dressed as an absence.
    """
    from src.scrapers.plugins.teenage_engineering import TeenageEngineeringScraper as TE

    page = "<div><span>1.7.3</span></div><div><span>OS update</span></div>"
    scraper, _ = _te_scraper({"https://teenage.engineering/downloads/op-1": page})
    result = await scraper.fetch_firmware_versions(
        "OP-1", "https://teenage.engineering/downloads/op-1"
    )

    assert [fw.version for fw in result.firmware_versions] == ["1.7.3"]
    assert result.firmware_versions[0].release_date is None


@pytest.mark.asyncio
async def test_te_fails_when_a_product_page_is_unreachable():
    from src.scrapers.plugins.teenage_engineering import TeenageEngineeringScraper as TE

    scraper, _ = _te_scraper({})
    result = await scraper.fetch_firmware_versions("OP-XY", "https://teenage.engineering/downloads/op-xy")

    assert result.success is False
