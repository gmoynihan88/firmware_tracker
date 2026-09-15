import pytest


def test_qsc_touchmix_models_map_to_their_own_firmware():
    """TouchMix-8/-16 share a build; the -30 Pro has its own.

    Matching on the family alone would give every model the first version listed.
    """
    from src.scrapers.plugins.qsc import QSCScraper

    text = (
        "Recommended TouchMix-8/-16 Firmware: 3.0.0955 "
        "Recommended TouchMix-30 Pro Firmware: 3.0.12462"
    )
    scraper = QSCScraper()

    assert scraper._touchmix_version_for("TouchMix-8", text) == "3.0.0955"
    assert scraper._touchmix_version_for("TouchMix-16", text) == "3.0.0955"
    assert scraper._touchmix_version_for("TouchMix-30 Pro", text) == "3.0.12462"
    assert scraper._touchmix_version_for("TouchMix-99", text) is None


def test_qsc_k2_version_applies_to_the_whole_series():
    """The K.2 page states one build for K8.2, K10.2 and K12.2 together."""
    from src.scrapers.plugins.qsc import QSCScraper

    match = QSCScraper.K2_VERSION.search(
        "Firmware version for all models: version 2.1.43 Firmware Updater App: version 2.2.6"
    )
    assert match and match.group(1) == "2.1.43"


@pytest.mark.asyncio
async def test_qsc_products_without_firmware_are_not_failures():
    """CP, KS and KLA publish no firmware, so empty is the correct answer."""
    from src.scrapers.plugins.qsc import QSCScraper

    scraper = QSCScraper()
    result = await scraper.fetch_firmware_versions("CP12", "https://example.invalid")

    assert result.success is True
    assert result.firmware_versions == []


QSC_K2_PAGE = """
    <p>Firmware version for all models: version 2.1.43</p>
    <p>Version 2.1 \u2013 8/11/2025</p>
    <p>K.2 Series Owner's Manual</p>
    <p>Revised 06/07/2017</p>
"""


def test_qsc_reads_the_k2_release_date():
    """The date is printed beside the version: "Version 2.1 - 8/11/2025".

    US month/day, so this is 11 August rather than 8 November. The value matches
    what the page's own listing shows.
    """
    from src.scrapers.plugins.qsc import QSCScraper

    date = QSCScraper()._k2_release_date(QSC_K2_PAGE)

    assert date.strftime("%Y-%m-%d") == "2025-08-11"


def test_qsc_does_not_take_a_document_revision_date():
    """The same page carries "Revised 06/07/2017" against a manual.

    An earlier implementation searched for the first date anywhere in the text, which
    on a page ordered the other way round would have dated 2025 firmware to 2017.
    """
    from src.scrapers.plugins.qsc import QSCScraper

    manual_first = """
        <p>K.2 Series Owner's Manual</p>
        <p>Revised 06/07/2017</p>
        <p>Firmware version for all models: version 2.1.43</p>
        <p>Version 2.1 \u2013 8/11/2025</p>
    """
    date = QSCScraper()._k2_release_date(manual_first)

    assert date.strftime("%Y-%m-%d") == "2025-08-11"

    # Nothing version-anchored means no date, rather than the nearest one available.
    assert QSCScraper()._k2_release_date("<p>Revised 06/07/2017</p>") is None


@pytest.mark.asyncio
async def test_qsc_touchmix_reports_no_date():
    """TouchMix pages date their installation instructions, not their firmware.

    "Windows Download and Installation / Revised 06/07/2017" sits beside firmware
    3.0.0955, and treating that as a release date would put a 2022 build in 2017.
    """
    from src.scrapers.plugins.qsc import QSCScraper

    scraper = QSCScraper()

    async def page(*args, **kwargs):
        return """
            <p>Windows Download and Installation</p><p>Revised 06/07/2017</p>
            <p>Recommended TouchMix-8/-16 Firmware: 3.0.0955</p>
        """

    scraper.fetch_page_js = page
    result = await scraper.fetch_firmware_versions("TouchMix-16", "https://example.invalid")

    assert result.success is True
    assert result.firmware_versions[0].version == "3.0.0955"
    assert result.firmware_versions[0].release_date is None


def test_qsc_malformed_date_degrades_to_none():
    from src.scrapers.plugins.qsc import QSCScraper

    assert QSCScraper()._k2_release_date("<p>Version 2.1 \u2013 13/45/2025</p>") is None
