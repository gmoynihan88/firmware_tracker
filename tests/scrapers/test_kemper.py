import pytest

from tests.support import _stub_fetch


def _kemper_page() -> str:
    """The download list and the release-notes modal behind it."""
    return """
    <ul class="downloads-list">
      <li class="panel"><h3>PROFILER Operating System 14.2.1 Release for all PROFILER models</h3>
        <div class="panel-footer"><span class="meta">Date: 2026-08-06, File size: 30.8 MB</span></div></li>
      <li class="panel"><h3>Rig Manager 4.2.13 for macOS</h3>
        <div class="panel-footer"><span class="meta">Date: 2026-08-06, File size: 265 MB</span></div></li>
      <li class="panel"><h3>Main Manual 14.2</h3>
        <div class="panel-footer"><span class="meta">Date: 2026-07-23, File size: 8.23 MB</span></div></li>
    </ul>
    <div class="modal-content"><div class="modal-body">
      <pre>PROFILER Operating System 14.2.1.67566
PROFILER Operating System 14.2.0.67476
PROFILER Operating System 14.1.2.66277</pre>
    </div></div>
    """


def test_kemper_takes_the_os_not_rig_manager_or_the_manual():
    """Rig Manager is the librarian app and "Main Manual 14.2" is a document."""
    from src.scrapers.plugins.kemper import KemperScraper

    versions = {fw.version for fw in KemperScraper()._parse(_kemper_page())}

    assert versions == {"14.2.1", "14.2.0", "14.1.2"}
    assert "4.2.13" not in versions, "took Rig Manager"


def test_kemper_dates_only_the_shipping_release():
    """The modal states no dates at all, so the history stays undated."""
    from src.scrapers.plugins.kemper import KemperScraper

    versions = KemperScraper()._parse(_kemper_page())
    by_version = {fw.version: fw for fw in versions}

    assert by_version["14.2.1"].release_date.strftime("%Y-%m-%d") == "2026-08-06"
    assert by_version["14.2.0"].release_date is None


def test_kemper_trims_the_build_number():
    """14.2.1.67566 in the modal and 14.2.1 in the list are one release."""
    from src.scrapers.plugins.kemper import KemperScraper

    versions = [fw.version for fw in KemperScraper()._parse(_kemper_page())]

    assert versions.count("14.2.1") == 1
    assert not any(v.count(".") > 2 for v in versions)


@pytest.mark.asyncio
async def test_kemper_lists_one_device_and_reads_the_page_once():
    """One OS covers every PROFILER model, so it is one device, not four."""
    from src.scrapers.plugins.kemper import KemperScraper

    scraper = KemperScraper()
    asked = _stub_fetch(scraper, {KemperScraper.DOWNLOADS_URL: _kemper_page()},
                        attr="fetch_page_js")

    devices = await scraper.fetch_device_list()
    result = await scraper.fetch_firmware_versions("PROFILER", "")

    assert [d.name for d in devices.devices] == ["PROFILER"]
    assert len(result.firmware_versions) == 3
    assert len(asked) == 1


@pytest.mark.asyncio
async def test_kemper_fails_when_no_operating_system_is_listed():
    """The page is JS-rendered; unrendered it has no version anywhere.

    Reporting success would read as Kemper having stopped publishing.
    """
    from src.scrapers.plugins.kemper import KemperScraper

    scraper = KemperScraper()
    _stub_fetch(scraper, {KemperScraper.DOWNLOADS_URL: "<html><body>nav only</body></html>"},
                attr="fetch_page_js")

    assert (await scraper.fetch_device_list()).success is False
