import pytest


PETERSON_HISTORY = """
<div class="firmwareResults results">
  <div class="faqItem firmwareEntry" data-update='{"product":"StroboClip HD","versionString":"1.0.6",
      "dateCreated":"April, 27 2020 09:00:00",
      "features":[{"feature":"Published note","public":1},{"feature":"Internal note","public":0}]}'></div>
  <div class="faqItem firmwareEntry" data-update='{"product":"StroboClip HDC","versionString":"1.0.15",
      "dateCreated":"March, 12 2024 09:00:00","features":[]}'></div>
  <div class="faqItem firmwareEntry" data-update='{"product":"StroboPLUS HD","versionString":"1.1.12",
      "dateCreated":"May, 04 2017 15:01:00","features":[]}'></div>
</div>
"""


def test_peterson_reads_the_embedded_firmware_json():
    """Each history entry carries the release as JSON in a data-update attribute.

    The previous scraper pointed at shop pages and stored manual revisions --
    "StroboStomp HD English v1.1" -- which is why four of six products reported 1.1.
    """
    from src.scrapers.plugins.peterson import PetersonScraper

    history = PetersonScraper()._parse_history(PETERSON_HISTORY)

    assert set(history) == {"stroboclip hd", "stroboclip hdc", "stroboplus hd"}
    entry = history["stroboclip hd"][0]
    assert entry.version == "1.0.6"
    assert entry.release_date.strftime("%Y-%m-%d") == "2020-04-27"
    # Unpublished notes are Peterson's internal record, not a changelog.
    assert entry.changelog == "Published note"


def test_peterson_keeps_stroboclip_hd_and_hdc_apart():
    """HD runs 1.0.1-1.0.6 and HDC runs 1.0.07-1.0.15, per Peterson's own data.

    The old scraper conflated them, leaving ten of HDC's versions on HD -- including
    the one marked latest, so the dashboard showed a version HD never had.
    """
    from src.scrapers.plugins.peterson import PetersonScraper

    history = PetersonScraper()._parse_history(PETERSON_HISTORY)

    assert [f.version for f in history["stroboclip hd"]] == ["1.0.6"]
    assert [f.version for f in history["stroboclip hdc"]] == ["1.0.15"]


@pytest.mark.asyncio
async def test_peterson_matches_the_vendors_casing():
    """Peterson writes StroboPLUS where the database has StroboPlus.

    Unnormalised, the scrape creates a second row and orphans the tracked one.
    """
    from src.scrapers.plugins.peterson import PetersonScraper

    scraper = PetersonScraper()
    scraper._history = scraper._parse_history(PETERSON_HISTORY)

    result = await scraper.fetch_firmware_versions("StroboPlus HD", scraper.SUPPORT_URL)

    assert result.success is True
    assert [f.version for f in result.firmware_versions] == ["1.1.12"]
