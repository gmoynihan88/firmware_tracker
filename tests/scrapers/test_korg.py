import pytest


def _korg_product_page() -> str:
    """A Downloads page, shaped like the real one.

    The Manuals entry is the trap that needs both filters: Grandstage X really does
    list "Korg System Updater Owner's Manual (English)", which matches the updater
    wording and is a PDF about the updater.
    """
    return """
    <div class="downloadInside">
      <div class="com_contents">
        <h3>Manuals</h3>
        <a class="tr"><div class="td dlFileTitle">
          <h3>minilogue xd/Owner&rsquo;s Manual (English)</h3><h3></h3>
          <small>2025.07.17 / PDF : 2.7MB</small>
        </div></a>
        <a class="tr"><div class="td dlFileTitle">
          <h3>Grandstage X/Korg System Updater Owner&rsquo;s Manual (English)</h3><h3></h3>
          <small>2024.02.01 / PDF : 1.1MB</small>
        </div></a>
      </div>
      <div class="com_contents">
        <h3>Software</h3>
        <a class="tr"><div class="td dlFileTitle">
          <h3>minilogue xd/Sound Librarian</h3><h3>1.0.5</h3>
          <small>2019.11.08 / ZIP : 17.5MB</small>
        </div></a>
        <a class="tr"><div class="td dlFileTitle">
          <h3>minilogue xd/System Updater</h3><h3>2.10</h3>
          <small>2020.03.10 / ZIP : 1.0MB</small>
        </div></a>
        <a class="tr"><div class="td dlFileTitle">
          <h3>minilogue xd/System Updater</h3><h3>2.10</h3>
          <small>2020.03.10 / DMG : 1.3MB</small>
        </div></a>
      </div>
      <div class="com_contents">
        <h3>Drivers</h3>
        <a class="tr"><div class="td dlFileTitle">
          <h3>minilogue xd/KORG USB-MIDI Driver (for Windows)</h3><h3>1.15 r63e</h3>
          <small>2026.01.20 / EXE : 6.4MB</small>
        </div></a>
      </div>
    </div>
    """


def _korg_version_in_name_page() -> str:
    """Two products that put the version in the entry name instead of its own heading."""
    return """
    <div class="com_contents">
      <h3>Software</h3>
      <a class="tr"><div class="td dlFileTitle">
        <h3>kaossilator 2/Operating System Update 1.08</h3>
        <small>2013.06.04 / ZIP : 3.0MB</small>
      </div></a>
    </div>
    """


def test_korg_takes_the_updater_not_the_librarian_or_the_driver():
    from src.scrapers.plugins.korg import KorgScraper

    versions = KorgScraper()._parse_product(_korg_product_page())
    found = {fw.version for fw in versions}

    assert found == {"2.10"}
    assert "1.0.5" not in found, "took the Sound Librarian"
    assert "1.15 r63e" not in found, "took the USB-MIDI driver"


def test_korg_ignores_a_manual_about_the_updater():
    """Matching the wording is not enough: it is in the Manuals section."""
    from src.scrapers.plugins.korg import KorgScraper

    versions = KorgScraper()._parse_product(_korg_product_page())

    assert all("Manual" not in (fw.version or "") for fw in versions)
    assert len(versions) == 1


def test_korg_reads_the_entrys_own_date():
    """"2020.03.10 / ZIP : 1.0MB" -- the size is not a version, the date is a date."""
    from src.scrapers.plugins.korg import KorgScraper

    versions = KorgScraper()._parse_product(_korg_product_page())

    assert versions[0].release_date.strftime("%Y-%m-%d") == "2020-03-10"


def test_korg_falls_back_to_a_version_in_the_name():
    """Korg writes the updater three ways and two put the version in the name."""
    from src.scrapers.plugins.korg import KorgScraper

    versions = KorgScraper()._parse_product(_korg_version_in_name_page())

    assert [fw.version for fw in versions] == ["1.08"]
    assert versions[0].release_date.strftime("%Y-%m-%d") == "2013-06-04"



def test_korg_reads_a_pa_arrangers_bare_operating_system_entry():
    """The Pa4X names its firmware "Operating System", with no "update" in it.

    The page loaded only after the timeout was raised, and then yielded nothing: the
    updater pattern needed "system updater" or "system update". The split download of
    OS 2.0, headed "1/5", and the SongBook Editor beside it are not firmware releases.
    """
    from src.scrapers.plugins.korg import KorgScraper

    page = """
    <div class="com_contents">
      <h3>Software</h3>
      <a class="tr"><div class="td dlFileTitle">
        <h3>Pa4X/Pa80 Card Converter</h3><h3>1.10</h3><small>2017.01.20 / ZIP : 3.7MB</small>
      </div></a>
      <a class="tr"><div class="td dlFileTitle">
        <h3>Pa4X/Operating System version 2.0 UPD divided version (for slow connections)</h3><h3>1/5</h3>
        <small>2017.06.30 / ZIP : 512.0MB</small>
      </div></a>
      <a class="tr"><div class="td dlFileTitle">
        <h3>Pa4X/Operating System version 2.0 PKG Full version (for fast connections)</h3><h3></h3>
        <small>2017/06/30</small>
      </div></a>
      <a class="tr"><div class="td dlFileTitle">
        <h3>Pa4X/Operating System</h3><h3>3.1.0</h3><small>2019.07.10 / ZIP : 184.9MB</small>
      </div></a>
      <a class="tr"><div class="td dlFileTitle">
        <h3>Pa4X/SongBook Editor v.3.0</h3><h3>3.0</h3><small>2018.12.10 / ZIP : 6.6MB</small>
      </div></a>
    </div>
    """

    versions = KorgScraper()._parse_product(page)

    assert [(fw.version, fw.release_date.strftime("%Y-%m-%d")) for fw in versions] == [("3.1.0", "2019-07-10")]

def test_korg_index_skips_discontinued_and_untracked_categories():
    """The index is a flat run of headings, so the walk has to track its own state."""
    from src.scrapers.plugins.korg import KorgScraper

    index = """
    <h3>Synthesizers / Keyboards</h3>
      <h4>on sale</h4>
        <a href="/us/support/download/product/0/811/">minilogue xd</a>
      <h4>Discontinued products</h4>
        <a href="/us/support/download/product/0/123/">MS2000</a>
    <h3>Tuners / Metronomes</h3>
      <h4>on sale</h4>
        <a href="/us/support/download/product/0/456/">TM-60</a>
    """

    found = KorgScraper()._index_candidates(index)

    assert [name for name, _url, _cat in found] == ["minilogue xd"]
    assert found[0][1].startswith("https://www.korg.com/")
    assert found[0][2] == "synthesizer"


def _korg_candidates(count=164):
    return [(f"Product {i:03d}", f"https://www.korg.com/p/{i:03d}/", "synthesizer")
            for i in range(count)]


def test_korg_batches_are_even_and_cover_everything_once():
    """Even sizes are the point: batching exists to give a predictable ceiling.

    Hashing each URL was the first approach and gave 41/33/56/34 on the real
    catalogue -- stable per product, but the worst batch is then 70% larger than the
    best and the ceiling it was meant to impose is gone.
    """
    from unittest.mock import patch

    from src.scrapers.plugins.korg import KorgScraper

    scraper = KorgScraper()
    candidates = _korg_candidates()
    seen, sizes = [], []

    for day in range(KorgScraper.BATCHES):
        with patch.object(KorgScraper, "_today_batch", lambda self, d=day: d):
            batch = scraper._select_batch(candidates)
        sizes.append(len(batch))
        seen.extend(url for _name, url, _cat in batch)

    assert sizes == [33, 33, 33, 33, 32]
    assert len(seen) == len(set(seen)) == 164, "a product was missed or checked twice"


def test_korg_full_sweep_takes_everything():
    """The catch-up path, off by default because it costs the full 794s.

    The day is pinned: batches are 33, 33, 33, 33 and 32, so asserting 33 against the
    real date failed one day in five -- first seen in CI on 2026-09-15.
    """
    from unittest.mock import patch

    from src.scrapers.plugins.korg import KorgScraper

    candidates = _korg_candidates()

    with patch.object(KorgScraper, "_today_batch", lambda self: 0):
        assert len(KorgScraper()._select_batch(candidates)) == 33
        assert len(KorgScraper(full_sweep=True)._select_batch(candidates)) == 164


def test_korg_full_sweep_reads_the_environment(monkeypatch):
    """The registry builds scrapers with no arguments, so an operator needs this."""
    from src.scrapers.plugins.korg import KorgScraper

    monkeypatch.setenv(KorgScraper.FULL_SWEEP_ENV, "1")
    assert KorgScraper()._full_sweep is True

    monkeypatch.setenv(KorgScraper.FULL_SWEEP_ENV, "0")
    assert KorgScraper()._full_sweep is False


def test_korg_batch_selection_is_stable_across_runs():
    """Sorted before striding, so the index's own ordering cannot reshuffle a batch.

    Korg's index is ordered for presentation. Striding it directly would move
    products between batches whenever that order changed, and a product could then
    go unchecked for far longer than five days.
    """
    import random

    from unittest.mock import patch

    from src.scrapers.plugins.korg import KorgScraper

    scraper = KorgScraper()
    candidates = _korg_candidates()
    shuffled = candidates[:]
    random.Random(3).shuffle(shuffled)

    with patch.object(KorgScraper, "_today_batch", lambda self: 2):
        first = scraper._select_batch(candidates)
        second = scraper._select_batch(shuffled)

    assert first == second


@pytest.mark.asyncio
async def test_korg_reports_not_checked_outside_todays_batch():
    """Not an empty success, which would claim Korg publishes nothing for it.

    Four days in five that claim would be false, and it would put the whole
    catalogue bar a fifth into devices_unexplained.
    """
    from src.scrapers.plugins.korg import KorgScraper

    scraper = KorgScraper()
    scraper._firmware = {"In Batch": []}

    result = await scraper.fetch_firmware_versions("Not In Batch", "")

    assert result.success is True
    assert result.not_checked is True
    assert result.firmware_versions == []


def _korg_index(*products) -> str:
    links = "\n".join(
        f'<a href="/us/support/download/product/0/{i}/">{name}</a>'
        for i, name in enumerate(products, start=100)
    )
    return f"""
    <h3>Synthesizers / Keyboards</h3>
      <h4>on sale</h4>
      {links}
    """


def _korg_scraper_with(pages, full_sweep=False):
    """A Korg scraper serving fixture pages, with batching switched off.

    BATCHES is set to 1 so a fixture of two products is not split across days --
    these tests are about what fetch_device_list keeps, not which fifth it picks.
    """
    from src.scrapers.plugins.korg import KorgScraper

    scraper = KorgScraper(full_sweep=full_sweep)
    scraper.BATCHES = 1
    fetched = []

    async def fake_fetch(url, **kwargs):
        fetched.append(url)
        return pages.get(url)

    scraper.fetch_page = fake_fetch
    return scraper, fetched


@pytest.mark.asyncio
async def test_korg_lists_only_products_that_publish_firmware():
    """The Focusrite lesson as code: a row that can never report a version is worse
    than no row. About half of Korg's current products carry an updater, so listing
    every candidate would add ~87 permanent blanks.
    """
    from src.scrapers.plugins.korg import KorgScraper

    pages = {
        KorgScraper.INDEX_URL: _korg_index("Has Firmware", "No Firmware"),
        "https://www.korg.com/us/support/download/product/0/100/": _korg_product_page(),
        "https://www.korg.com/us/support/download/product/0/101/":
            '<div class="com_contents"><h3>Manuals</h3>'
            '<div class="td dlFileTitle"><h3>No Firmware/Owner\'s Manual</h3><h3></h3>'
            '<small>2024.01.01 / PDF : 1MB</small></div></div>',
    }
    scraper, _fetched = _korg_scraper_with(pages)

    result = await scraper.fetch_device_list()

    assert result.success is True
    assert [d.name for d in result.devices] == ["Has Firmware"]


@pytest.mark.asyncio
async def test_korg_device_list_is_fetched_once_per_run():
    """fetch_firmware_versions reads what the device pass already collected.

    Without the cache the firmware pass would refetch every product page, doubling
    a cost this scraper is already batching to control.
    """
    from src.scrapers.plugins.korg import KorgScraper

    pages = {
        KorgScraper.INDEX_URL: _korg_index("Has Firmware"),
        "https://www.korg.com/us/support/download/product/0/100/": _korg_product_page(),
    }
    scraper, fetched = _korg_scraper_with(pages)

    await scraper.fetch_device_list()
    assert len(fetched) == 2  # the index, then the one product

    await scraper.fetch_device_list()
    result = await scraper.fetch_firmware_versions("Has Firmware", "")

    assert len(fetched) == 2, "refetched pages it already had"
    assert [fw.version for fw in result.firmware_versions] == ["2.10"]


@pytest.mark.asyncio
async def test_korg_fails_loudly_when_the_index_is_unreachable():
    """An empty device list would read as a vendor that stopped publishing."""
    from src.scrapers.plugins.korg import KorgScraper

    scraper, _ = _korg_scraper_with({KorgScraper.INDEX_URL: None})
    result = await scraper.fetch_device_list()

    assert result.success is False
    assert KorgScraper.INDEX_URL in result.error


@pytest.mark.asyncio
async def test_korg_fails_when_the_index_shape_changes():
    """A page that loads but yields no candidates means the headings moved.

    Reporting success with nothing would quietly empty the catalogue's view of Korg
    on the day the markup changes.
    """
    from src.scrapers.plugins.korg import KorgScraper

    scraper, _ = _korg_scraper_with(
        {KorgScraper.INDEX_URL: "<h3>Synthesizers / Keyboards</h3><p>nothing here</p>"}
    )
    result = await scraper.fetch_device_list()

    assert result.success is False
    assert "no current products" in result.error


@pytest.mark.asyncio
async def test_korg_skips_a_product_page_that_fails_to_load():
    """One dead page must not take the whole run with it."""
    from src.scrapers.plugins.korg import KorgScraper

    pages = {
        KorgScraper.INDEX_URL: _korg_index("Good", "Dead"),
        "https://www.korg.com/us/support/download/product/0/100/": _korg_product_page(),
        "https://www.korg.com/us/support/download/product/0/101/": None,
    }
    scraper, _ = _korg_scraper_with(pages)

    result = await scraper.fetch_device_list()

    assert result.success is True
    assert [d.name for d in result.devices] == ["Good"]



@pytest.mark.asyncio
async def test_korg_gives_product_pages_longer_than_the_default_timeout():
    """The Pa4X's page takes 31s, one over the 30s default, and was dropped every run."""
    from src.scrapers.plugins.korg import KorgScraper

    scraper = KorgScraper()
    scraper.BATCHES = 1
    calls = []

    async def fake_fetch(url, **kwargs):
        calls.append((url, kwargs.get("timeout")))
        if url == KorgScraper.INDEX_URL:
            return _korg_index("Slow Page")
        return _korg_product_page()

    scraper.fetch_page = fake_fetch
    await scraper.fetch_device_list()

    assert calls[0] == (KorgScraper.INDEX_URL, None)
    assert calls[1][1] == KorgScraper.PRODUCT_PAGE_TIMEOUT > 31

@pytest.mark.asyncio
async def test_korg_firmware_lookup_loads_the_catalogue_if_asked_first():
    """A caller that skips fetch_device_list still gets an answer, or the error.

    The service always calls the device list first, but scripts and the debugging
    commands in the skill call fetch_firmware_versions directly. Swallowing an index
    failure here would turn a broken vendor into a silent empty result.
    """
    from src.scrapers.plugins.korg import KorgScraper

    pages = {
        KorgScraper.INDEX_URL: _korg_index("Has Firmware"),
        "https://www.korg.com/us/support/download/product/0/100/": _korg_product_page(),
    }
    scraper, _ = _korg_scraper_with(pages)
    result = await scraper.fetch_firmware_versions("Has Firmware", "")
    assert [fw.version for fw in result.firmware_versions] == ["2.10"]

    broken, _ = _korg_scraper_with({KorgScraper.INDEX_URL: None})
    failed = await broken.fetch_firmware_versions("Anything", "")
    assert failed.success is False
    assert KorgScraper.INDEX_URL in failed.error
