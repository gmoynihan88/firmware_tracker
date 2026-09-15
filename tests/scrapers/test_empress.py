import pytest


def _empress_current() -> str:
    return """
    <div class="firmware-updates">
      <div class="firmware-product"><h3>Echosystem</h3>
        <div class="firmware-product__buttons">
          <a class="firmware-product__button" href="/f/eees0250.bin">Download Firmware (v2.50)</a>
          <a href="/blogs/support-echosystem/updating">Installation Instructions</a>
        </div></div>
      <div class="firmware-product"><h3>ZOIA</h3>
        <div class="firmware-product__buttons">
          <a class="firmware-product__button" href="/f/eezo0541.bin">Download Firmware (v5.41)</a>
        </div></div>
    </div>
    """


def _empress_archive() -> str:
    return """
    <div class="old-firmware-product" id="echosystem"><h3>Echosystem</h3>
      <ul class="old-firmware-product__list">
        <li class="old-firmware-product__item"><a href="/f/a">Firmware v2.42</a> — Released 2025-11-14</li>
        <li class="old-firmware-product__item"><a href="/f/b">Firmware v2.20</a> — Released 2025-04-24</li>
      </ul></div>
    <div class="old-firmware-product" id="zoia"><h3>ZOIA</h3>
      <ul class="old-firmware-product__list">
        <li class="old-firmware-product__item"><a href="/f/c">Firmware v5.32</a> — Released 2025-12-15</li>
      </ul></div>
    """


def _empress_scraper(current=None, archive=None):
    from src.scrapers.plugins.empress import EmpressEffectsScraper as E

    scraper = E()
    pages = {
        E.CURRENT_URL: _empress_current() if current is None else current,
        E.ARCHIVE_URL: _empress_archive() if archive is None else archive,
    }

    async def fake_fetch_js(url, **kwargs):
        return pages.get(url)

    scraper.fetch_page_js = fake_fetch_js
    return scraper


@pytest.mark.asyncio
async def test_empress_merges_the_shipping_version_with_the_archive():
    """Newest first, and the shipping release leads even though it has no date."""
    scraper = _empress_scraper()
    result = await scraper.fetch_firmware_versions("Echosystem", "")

    assert [fw.version for fw in result.firmware_versions] == ["2.50", "2.42", "2.20"]
    assert result.firmware_versions[1].release_date.strftime("%Y-%m-%d") == "2025-11-14"


@pytest.mark.asyncio
async def test_empress_leaves_the_shipping_version_undated():
    """The page states no date for it, and the archive's newest belongs to v2.42.

    Borrowing that date would put 2025-11-14 against v2.50, eight releases later.
    """
    scraper = _empress_scraper()
    result = await scraper.fetch_firmware_versions("Echosystem", "")

    assert result.firmware_versions[0].version == "2.50"
    assert result.firmware_versions[0].release_date is None


@pytest.mark.asyncio
async def test_empress_still_reports_the_current_version_without_the_archive():
    """The archive is history; losing it must not lose the answer to "am I behind"."""
    scraper = _empress_scraper(archive="<html><body>maintenance</body></html>")
    result = await scraper.fetch_firmware_versions("ZOIA", "")

    assert [fw.version for fw in result.firmware_versions] == ["5.41"]


@pytest.mark.asyncio
async def test_empress_fails_when_the_firmware_section_is_missing():
    """A plain fetch returns a shell with no firmware section at all.

    Reporting success on that would read as a vendor that stopped publishing,
    which is what the unrendered page looks like.
    """
    scraper = _empress_scraper(current="<html><body><nav>Products</nav></body></html>")
    result = await scraper.fetch_device_list()

    assert result.success is False


@pytest.mark.asyncio
async def test_empress_does_not_duplicate_a_version_present_on_both_pages():
    """If the archive ever lists the shipping release too, it must appear once."""
    archive = _empress_archive().replace(
        "Firmware v2.42</a> — Released 2025-11-14",
        "Firmware v2.50</a> — Released 2026-01-05",
    )
    scraper = _empress_scraper(archive=archive)
    versions = (await scraper.fetch_firmware_versions("Echosystem", "")).firmware_versions

    assert [fw.version for fw in versions] == ["2.50", "2.20"]
    # The shipping entry wins, so no invented date sneaks in from the archive.
    assert versions[0].release_date is None
