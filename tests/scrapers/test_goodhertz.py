import pytest

from tests.support import _stub_fetch


def _gh_downloads(heading="3.14.1", installer="3.14.1", date="June 30, 2026"):
    """The downloads page: one bundle heading, its date, installers, notes."""
    return (
        f'<h2 class="center bundle-name">Goodhertz {heading}</h2>'
        f'<h3 class="center release-date">{date}</h3>'
        f'<a href="/download/Goodhertz-Installer-{installer}-35869a1.exe/">Windows</a>'
        f'<a href="/download/Goodhertz-Installer-{installer}-35869a1.pkg/">Mac</a>'
        '<div class="release-notes"><h3>Installation Notes</h3><ul>'
        "<li>This is a 64-bit download and requires a 64-bit DAW and macOS 10.13+ or Windows 10+.</li></ul></div>"
        '<div class="release-notes"><h3>Release Notes</h3><ul>'
        "<li>Fixed a buffering issue in VCME for very high sample rates (≥ 384 kHz)</li>"
        "<li>Improved AAX page tables</li></ul></div>"
    )


def test_goodhertz_reads_the_bundle_version_with_its_date_and_notes():
    """Release notes, not the installation notes that share their markup and come first."""
    from src.scrapers.plugins.goodhertz import GoodhertzScraper

    release = GoodhertzScraper()._parse(_gh_downloads())

    assert (release.version, release.release_date.date().isoformat()) == ("3.14.1", "2026-06-30")
    assert release.changelog.splitlines() == [
        "- Fixed a buffering issue in VCME for very high sample rates (≥ 384 kHz)",
        "- Improved AAX page tables",
    ]


def test_goodhertz_trusts_the_installer_over_a_stale_heading_and_drops_its_date():
    """The date and notes belong to the heading's release, not the file's."""
    from src.scrapers.plugins.goodhertz import GoodhertzScraper

    release = GoodhertzScraper()._parse(_gh_downloads(heading="3.14.1", installer="3.14.2"))

    assert (release.version, release.release_date, release.changelog) == ("3.14.2", None, None)


def test_goodhertz_does_not_read_the_build_hash_or_os_requirements_as_versions():
    from src.scrapers.plugins.goodhertz import GoodhertzScraper

    page = _gh_downloads().replace("Goodhertz 3.14.1</h2>", "Downloads</h2>").replace("-3.14.1-", "-")

    assert GoodhertzScraper()._parse(page) is None


@pytest.mark.asyncio
async def test_goodhertz_lists_one_bundle_device_from_one_fetch():
    from src.scrapers.plugins.goodhertz import GoodhertzScraper as GH

    scraper = GH()
    asked = _stub_fetch(scraper, {GH.DOWNLOADS_URL: _gh_downloads()})

    devices = (await scraper.fetch_device_list()).devices
    result = await scraper.fetch_firmware_versions(devices[0].name, devices[0].firmware_page_url)

    assert asked == [GH.DOWNLOADS_URL]
    assert [(d.name, d.category) for d in devices] == [("Goodhertz Plugins", "vst_plugin")]
    assert [fw.version for fw in result.firmware_versions] == ["3.14.1"]


@pytest.mark.asyncio
async def test_goodhertz_fails_loudly_when_the_page_has_no_version():
    from src.scrapers.plugins.goodhertz import GoodhertzScraper as GH

    scraper = GH()
    _stub_fetch(scraper, {GH.DOWNLOADS_URL: "<h2>Please login</h2>"})

    assert (await scraper.fetch_device_list()).success is False
