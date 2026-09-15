import pytest


def test_modartt_parses_only_changelog_titles():
    """Versions come from the title divs, not from free text in descriptions.

    Descriptions mention version-like strings that are not Pianoteq releases, so
    scanning raw text invents versions such as an OS number.
    """
    from src.scrapers.plugins.modartt import ModarttScraper

    html = """
    <div class="mrt-title">9.2.5 (2026/09/09)</div>
    <div class="mrt-body">Fix a regression. Requires macOS 10.3.9 or later.</div>
    <div class="mrt-title">9.2.4 (2026/08/25)</div>
    <div class="mrt-body">Improved sustain modelling.</div>
    """
    versions = ModarttScraper()._parse_changelog(html)

    assert [fw.version for fw in versions] == ["9.2.5", "9.2.4"]
    assert versions[0].release_date.strftime("%Y-%m-%d") == "2026-09-09"
    assert "regression" in versions[0].changelog


def test_modartt_major_version_prefix_filters_editions():
    """Stage, Standard and Pro share their major version's builds."""
    from src.scrapers.plugins.modartt import ModarttScraper

    scraper = ModarttScraper()
    assert scraper._major_version_prefix("Pianoteq 9 Pro") == "9."
    assert scraper._major_version_prefix("Pianoteq 8 Stage") == "8."


@pytest.mark.asyncio
async def test_modartt_reports_failure_rather_than_stale_fallback():
    """If the API cannot be read the scrape fails, instead of serving a static table.

    A silent static fallback is how this scraper came to report 9.2.4 as current
    while Modartt was shipping 9.2.5.
    """
    from src.scrapers.plugins.modartt import ModarttScraper

    scraper = ModarttScraper()

    async def _no_payload():
        return None

    scraper._fetch_products_payload = _no_payload
    result = await scraper.fetch_firmware_versions("Pianoteq 9", "https://example.invalid")

    assert result.success is False
    assert not result.firmware_versions
