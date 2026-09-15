import pytest

from tests.support import _stub_fetch


def _kh_changelog(*entries):
    """The changelog: a section per release, version and date in one heading."""
    return "<h1>Kilohearts Plugins Changelog</h1>" + "".join(
        f'<section id="{version}"><content>'
        f'<h3><a href="/changelog#{version}">{version}</a> <span style="font-size: 60%;"> - {date}</span></h3>'
        "<p><h4>Phase Plant</h4><br> - Fixed presets saved in 3.2.1 of a host loading wrongly."
        "<h4>macOS</h4><br> - Requires macOS 10.13 or later.</p></content></section>"
        for version, date in entries
    )


KH_DOWNLOAD = ("<p>Download the Installer</p><p>Kilohearts Installer</p><p>2.4.6 for Windows</p>"
               "<p>Kilohearts Installer</p><p>2.4.6 for Mac</p>")


def test_kilohearts_reads_each_release_heading_and_nothing_under_it():
    """The notes under a release mention 3.2.1 and macOS 10.13; neither is a release."""
    from src.scrapers.plugins.kilohearts import KiloheartsScraper

    versions = KiloheartsScraper()._parse_changelog(_kh_changelog(
        ("2.4.6", "March 10, 2026"),
        ("2.4.5", "December 11, 2025"),
        ("1.5.0", "November 1, 2018"),
    ))

    assert [(fw.version, fw.release_date.date().isoformat()) for fw in versions] == [
        ("2.4.6", "2026-03-10"),
        ("2.4.5", "2025-12-11"),
        ("1.5.0", "2018-11-01"),
    ]


def test_kilohearts_reads_the_installer_version_from_the_download_page():
    from src.scrapers.plugins.kilohearts import KiloheartsScraper

    assert KiloheartsScraper()._installer_version(KH_DOWNLOAD) == "2.4.6"


@pytest.mark.asyncio
async def test_kilohearts_adds_an_installer_newer_than_the_changelog():
    """Undated, because the changelog -- the only dated source -- has not caught up."""
    from src.scrapers.plugins.kilohearts import KiloheartsScraper as KH

    scraper = KH()
    _stub_fetch(scraper, {
        KH.CHANGELOG_URL: _kh_changelog(("2.4.6", "March 10, 2026")),
        KH.DOWNLOAD_URL: KH_DOWNLOAD.replace("2.4.6", "2.4.7"),
    })

    result = await scraper.fetch_firmware_versions(KH.PRODUCT_NAME, KH.CHANGELOG_URL)

    assert [(fw.version, fw.release_date is not None) for fw in result.firmware_versions] == [
        ("2.4.7", False),
        ("2.4.6", True),
    ]


@pytest.mark.asyncio
async def test_kilohearts_lists_the_suite_as_one_device_from_two_fetches():
    from src.scrapers.plugins.kilohearts import KiloheartsScraper as KH

    scraper = KH()
    asked = _stub_fetch(scraper, {
        KH.CHANGELOG_URL: _kh_changelog(("2.4.6", "March 10, 2026"), ("2.4.5", "December 11, 2025")),
        KH.DOWNLOAD_URL: KH_DOWNLOAD,
    })

    devices = (await scraper.fetch_device_list()).devices
    result = await scraper.fetch_firmware_versions(devices[0].name, devices[0].firmware_page_url)

    assert sorted(asked) == sorted([KH.CHANGELOG_URL, KH.DOWNLOAD_URL])
    assert [(d.name, d.category) for d in devices] == [("Kilohearts Plugins", "vst_plugin")]
    assert [fw.version for fw in result.firmware_versions] == ["2.4.6", "2.4.5"]  # no duplicate


@pytest.mark.asyncio
async def test_kilohearts_still_reports_the_changelog_without_the_download_page():
    from src.scrapers.plugins.kilohearts import KiloheartsScraper as KH

    scraper = KH()
    _stub_fetch(scraper, {KH.CHANGELOG_URL: _kh_changelog(("2.4.6", "March 10, 2026"))})

    assert (await scraper.fetch_device_list()).success is True


@pytest.mark.asyncio
async def test_kilohearts_fails_loudly_without_the_changelog():
    from src.scrapers.plugins.kilohearts import KiloheartsScraper as KH

    scraper = KH()
    _stub_fetch(scraper, {KH.DOWNLOAD_URL: KH_DOWNLOAD})

    assert (await scraper.fetch_device_list()).success is False
