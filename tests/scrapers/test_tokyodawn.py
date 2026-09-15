import pytest

from tests.support import _stub_fetch


def _tdr_page(name, latest=None, download=None, changelog=None):
    """A product page: title, download buttons, "Latest version", hidden changelog."""
    parts = [f"<html><head><title>{name} | Tokyo Dawn Records</title></head><body>"]
    if download:
        folder = name.replace("TDR ", "").replace(" ", "")
        parts.append(f'<a class="downloadbutton" href="https://www.tokyodawn.net/labs/{folder}/{download}/{name}.zip">Macos Package</a>')
    if latest:
        parts.append(f'<p class="margintop">Latest version: <strong>{latest}</strong> <a class="changelog" href="#">(Changelog)</a></p>')
    if changelog:
        parts.append(f'<div class="changelogcontent" style="display: none">{changelog}</div>')
    parts.append("<p>Requires macOS 10.11 or later.</p></body></html>")
    return "".join(parts)


TDR_NOVA_CHANGELOG = (
    "2.2.2 Hotfix<br/><br/># Fixed a bug affecting host undo history<br/><br/><br/>"
    "2.2.1 Maintenance update<br/><br/># Added optional smoothing<br/># Fixed human smoothing (broken by 1.1.3)<br/><br/><br/>"
    "1.0.0 Initial release<br/><br/># First public version"
)


def test_tdr_reads_every_changelog_entry_with_its_own_notes():
    """Entries start with the version; notes start with "#", even when they name one."""
    from src.scrapers.plugins.tokyodawn import TokyoDawnScraper

    name, versions = TokyoDawnScraper()._parse_product(
        _tdr_page("TDR Nova", latest="2.2.2", download="2.2.2", changelog=TDR_NOVA_CHANGELOG)
    )

    assert name == "TDR Nova"
    assert [fw.version for fw in versions] == ["2.2.2", "2.2.1", "1.0.0"]
    assert versions[1].changelog.splitlines() == [
        "# Added optional smoothing",
        "# Fixed human smoothing (broken by 1.1.3)",
    ]
    assert all(fw.release_date is None for fw in versions)


def test_tdr_trusts_the_download_over_the_latest_version_text():
    """The download path is the artefact; a newer build missing from the changelog tops it, without notes."""
    from src.scrapers.plugins.tokyodawn import TokyoDawnScraper

    _name, versions = TokyoDawnScraper()._parse_product(
        _tdr_page("TDR Nova", latest="2.2.1", download="2.2.3", changelog=TDR_NOVA_CHANGELOG)
    )

    assert [fw.version for fw in versions] == ["2.2.3", "2.2.2", "2.2.1", "1.0.0"]
    assert versions[0].changelog is None


TDR_LABS = (
    '<a href="//www.tokyodawn.net/tdr-nova/">TDR Nova</a>'
    '<a href="https://www.tokyodawn.net/tdr-nova-ge/">TDR Nova GE</a>'
    '<a href="https://www.tokyodawn.net/tdr-nova/">TDR Nova again</a>'
    '<a href="//www.tokyodawn.net/tdr-collector/">TDR Collector</a>'
    '<a href="https://www.tokyodawn.net/tdr-everything-bundle/">Bundle</a>'
    '<a href="//www.tokyodawn.net/the_move3/">A record</a>'
)


def _tdr_site():
    from src.scrapers.plugins.tokyodawn import TokyoDawnScraper as TDR

    base = TDR.manufacturer_website
    return {
        TDR.LABS_URL: TDR_LABS,
        f"{base}/tdr-nova/": _tdr_page("TDR Nova", "2.2.2", "2.2.2", TDR_NOVA_CHANGELOG),
        f"{base}/tdr-nova-ge/": _tdr_page("TDR Nova GE", "2.2.2", "2.2.2", "2.2.2 Hotfix<br/># Fix"),
        f"{base}/tdr-collector/": _tdr_page("TDR Collector", "1.0.10", "1.0.10", "1.0.10 Maintenance Update<br/># Fix"),
        f"{base}/tdr-everything-bundle/": _tdr_page("TDR Production Bundle"),
    }


@pytest.mark.asyncio
async def test_tdr_lists_each_edition_once_and_skips_the_bundles():
    """GE editions are their own products; bundles have no version; Collector is not a plug-in."""
    from src.scrapers.plugins.tokyodawn import TokyoDawnScraper as TDR

    scraper = TDR()
    asked = _stub_fetch(scraper, _tdr_site())

    devices = (await scraper.fetch_device_list()).devices

    assert [(d.name, d.category) for d in devices] == [
        ("TDR Nova", "vst_plugin"),
        ("TDR Nova GE", "vst_plugin"),
        ("TDR Collector", "other"),
    ]
    assert len(asked) == 5  # the labs page and four product pages, each once
    assert all("the_move3" not in url for url in asked)


@pytest.mark.asyncio
async def test_tdr_fails_the_listing_when_a_product_page_does_not_load():
    from src.scrapers.plugins.tokyodawn import TokyoDawnScraper as TDR

    scraper = TDR()
    site = _tdr_site()
    del site[f"{TDR.manufacturer_website}/tdr-nova-ge/"]
    _stub_fetch(scraper, site)

    assert (await scraper.fetch_device_list()).success is False
