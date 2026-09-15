import pytest


EVENTIDE_H910_PAGE = """
<div class="download card h910-harmonizer">
  <a class="download-link">H910/H910 Dual Installer (Mac 64-bit)</a>
  <div class="version-number">Version 3.12.4 </div>
  <div class="card-body"><h2>Release Notes</h2>
    <h3>3.12.4</h3><ul><li>Screen reader support</li></ul>
    <h3>3.11.0</h3><ul><li>Older release</li></ul>
  </div>
</div>
<div class="download card 2016-stereo-room h910-harmonizer">
  <a class="download-link">PreSonus Promotion Installer (Mac 64-bit)</a>
  <div class="version-number">Version 2.5.11</div>
</div>
<div class="download card h910-harmonizer">
  <a class="download-link">H910 Plug-in User Guide</a>
  <div class="version-number">Version 8 | English</div>
</div>
"""


def test_eventide_ignores_another_products_installer_on_the_same_page():
    """The H910 page carries a PreSonus installer tagged with H910's own slug.

    Both cards claim the product, so the class alone does not decide it. Taking the
    wrong one would report 2.5.11 as H910's version -- a real number, from a real
    installer, for a different product.
    """
    from src.scrapers.plugins.eventide import EventideScraper

    versions = EventideScraper()._installer_versions(EVENTIDE_H910_PAGE, "H910 Harmonizer")

    assert [fw.version for fw in versions] == ["3.12.4", "3.11.0"]


def test_eventide_skips_user_guide_revisions():
    """"Version 8 | English" is a manual revision, not a release."""
    from src.scrapers.plugins.eventide import EventideScraper

    versions = EventideScraper()._installer_versions(EVENTIDE_H910_PAGE, "H910 Harmonizer")

    assert "8" not in [fw.version for fw in versions]


def test_eventide_reads_both_heading_levels_for_history():
    """Blackhole nests versions as h3 under an h2; H90 makes each version an h2.

    Reading one level returns a single version for half the catalogue.
    """
    from src.scrapers.plugins.eventide import EventideScraper

    h2_style = """
    <div class="download card widget">
      <a class="download-link">Widget Installer (Mac 64-bit)</a>
      <div class="version-number">Version 2.2.0</div>
      <div class="card-body">
        <h2>2.2.0</h2><ul><li>New</li></ul>
        <h3>Firmware Requirements</h3><ul><li>H90: 1.9.4+</li></ul>
        <h2>2.1.8</h2><ul><li>Older</li></ul>
      </div>
    </div>
    """
    versions = EventideScraper()._installer_versions(h2_style, "Widget")

    # The "Firmware Requirements" heading and the 1.9.4+ inside it are not releases.
    assert [fw.version for fw in versions] == ["2.2.0", "2.1.8"]


def test_eventide_untitled_card_is_used_only_when_unambiguous():
    """Obliterate's cards carry a version and no title element at all."""
    from src.scrapers.plugins.eventide import EventideScraper

    lone = """
    <div class="download card obliterate"><div class="version-number">Version 1.1.4</div></div>
    <div class="download card obliterate"><div class="version-number">Version 1.1.4</div></div>
    """
    assert [fw.version for fw in EventideScraper()._installer_versions(lone, "Obliterate")] == ["1.1.4"]

    # Two different untitled versions are ambiguous, so nothing is claimed.
    conflicting = """
    <div class="download card obliterate"><div class="version-number">Version 1.1.4</div></div>
    <div class="download card obliterate"><div class="version-number">Version 9.9.9</div></div>
    """
    assert EventideScraper()._installer_versions(conflicting, "Obliterate") == []


def test_eventide_strips_zero_width_marks_from_names():
    """Omnipressor's installer title carries a zero-width joiner before the name.

    It is invisible everywhere except a string comparison, which is how a scrape
    silently creates a second row beside the one your devices are attached to.
    """
    from src.scrapers.plugins.eventide import EventideScraper

    assert EventideScraper._normalise_name("\u200dOmnipressor\u00ae") == "Omnipressor"
    assert EventideScraper._normalise_name("Blackhole\u00ae") == "Blackhole"
    assert EventideScraper._slug("H910 Harmonizer") == "h910-harmonizer"


@pytest.mark.asyncio
async def test_eventide_hardware_reports_no_version_without_fetching():
    """Eventide publishes no pedal firmware version, so none is claimed.

    The H90 page's most prominent version belongs to Eventide Control, and the next
    to H90 Control, whose notes read "Requires H90 firmware 1.9.4+". Both are
    companion apps on their own numbering. Fetching the page cannot help, so it is
    not fetched.
    """
    from src.scrapers.plugins.eventide import EventideScraper

    scraper = EventideScraper()
    scraper._categories = {"H90": "pedal", "Blackhole": "plug-in"}

    async def fail(*args, **kwargs):
        raise AssertionError("hardware must not trigger a fetch")

    scraper.fetch_page = fail

    result = await scraper.fetch_firmware_versions("H90", "https://example.invalid")

    assert result.success is True      # success, not failure: nothing broke
    assert result.firmware_versions == []
