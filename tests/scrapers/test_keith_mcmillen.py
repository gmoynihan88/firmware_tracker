import pytest


def _kmi_page() -> str:
    return """
    <h3>Firmware Downloads</h3>
    <h4>SendSysEx</h4>
    <p>v1.3.0; command line utility that can update KMI product firmware.</p>
    <h3>K-Board Downloads</h3>
    <h4>K-Board Editor for Mac</h4><p>K-Board Editor v1.3.0 for Mac</p>
    <h3>BopPad Downloads</h3>
    <h4>BopPad Editor for Mac</h4><p>BopPad Editor v1.2.0 for Mac</p>
    <h3>K-Mix Downloads</h3>
    """


def test_kmi_reads_products_from_the_downloads_headings():
    from src.scrapers.plugins.keith_mcmillen import KeithMcMillenScraper as KMI

    assert KMI()._parse_products(_kmi_page()) == ["K-Board", "BopPad", "K-Mix"]


def test_kmi_does_not_treat_the_firmware_heading_as_a_product():
    """"Firmware Downloads" matches the pattern and introduces SendSysEx, a utility."""
    from src.scrapers.plugins.keith_mcmillen import KeithMcMillenScraper as KMI

    assert "Firmware" not in KMI()._parse_products(_kmi_page())


@pytest.mark.asyncio
async def test_kmi_reports_no_version_and_says_why():
    """The editors are versioned and the instruments are not.

    Reporting "K-Board Editor v1.3.0" as the K-Board's firmware is the companion-app
    trap, which this page sets about twenty times. Every product is flagged
    not_published so the catalogue explains the blank instead of looking broken.
    """
    from src.scrapers.plugins.keith_mcmillen import KeithMcMillenScraper as KMI

    scraper = KMI()

    async def fake_fetch(url, **kwargs):
        return _kmi_page()

    scraper.fetch_page = fake_fetch

    devices = await scraper.fetch_device_list()
    assert {d.firmware_availability for d in devices.devices} == {"not_published"}
    assert {d.category for d in devices.devices} == {"midi_controller", "audio_interface"}

    result = await scraper.fetch_firmware_versions("K-Board", "")
    assert result.success is True
    assert result.firmware_versions == []
