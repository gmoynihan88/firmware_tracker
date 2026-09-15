import pytest


def _entry(product, version, stamp, notes, data_update):
    items = "".join(f"<li>{note}</li>" for note in notes)
    return f"""
  <div class="faqItem faqEntry closed firmwareEntry model5" data-update='{data_update}'>
    <div class="info">
      <h3 onclick="toggleFaq(event)">{product} Version {version}</h3>
      <div>
        <p class="dateTime">{stamp}</p>
        <ul>{items}</ul>
        <button class="redButton firmwareInstallButton connectable"></button>
      </div>
    </div>
  </div>"""


# Built from the live page. The first entry is the one whose JSON breaks: its note
# holds an apostrophe, which ends the single-quoted data-update attribute early.
PETERSON_HISTORY = '<div class="firmwareResults results">' + "".join([
    _entry("StroboStomp HD", "1.0.34", "Friday, May 2, 2025 11:39:25 AM EDT",
           ["New settings screen parameter for 'Power Up Mute State'"],
           '{"product":"StroboStomp HD","versionString":"1.0.34","features":[{"feature":"New settings screen parameter for \'Power Up Mute State\'","public":1}]}'),
    _entry("StroboStomp HD", "1.0.33", "Thursday, July 20, 2023 7:08:00 PM EDT",
           ["Various Bug Fixes and Improvements"],
           '{"product":"StroboStomp HD","versionString":"1.0.33"}'),
    _entry("StroboClip HD", "1.0.6", "Monday, April 27, 2020 9:00:00 AM EDT",
           ["Published note"], '{"product":"StroboClip HD","versionString":"1.0.6"}'),
    _entry("StroboClip HDC", "1.0.15", "Tuesday, March 12, 2024 9:00:00 AM EDT",
           [], '{"product":"StroboClip HDC","versionString":"1.0.15"}'),
    _entry("StroboPLUS HD", "1.1.12", "Thursday, May 4, 2017 3:01:00 PM EDT",
           [], '{"product":"StroboPLUS HD","versionString":"1.1.12"}'),
]) + "</div>"


def _scraper_on(html):
    from src.scrapers.plugins.peterson import PetersonScraper

    scraper = PetersonScraper()

    async def _page(url, *_args, **_kwargs):
        return html if url == scraper.SUPPORT_URL else None

    scraper.fetch_page = _page
    return scraper


@pytest.mark.asyncio
async def test_peterson_reads_a_release_whose_json_attribute_is_broken():
    """StroboStomp HD 1.0.34 was dropped for over a year.

    Its note contains an apostrophe, which ends the single-quoted data-update
    attribute, so the JSON failed to parse and the entry was skipped. The visible
    heading, date and notes carry the same release.
    """
    scraper = _scraper_on(PETERSON_HISTORY)

    result = await scraper.fetch_firmware_versions("StroboStomp HD", scraper.SUPPORT_URL)

    assert result.success is True
    latest = result.firmware_versions[0]
    assert latest.version == "1.0.34"
    assert latest.release_date.strftime("%Y-%m-%d") == "2025-05-02"
    assert latest.changelog == "New settings screen parameter for 'Power Up Mute State'"


@pytest.mark.asyncio
async def test_peterson_lists_the_tuners_its_firmware_history_names():
    """The catalogue is the history's products, not a list kept by hand."""
    scraper = _scraper_on(PETERSON_HISTORY)

    result = await scraper.fetch_device_list()

    assert result.success is True
    devices = {d.name: d.category for d in result.devices}
    assert list(devices) == ["StroboStomp HD", "StroboClip HD", "StroboClip HDC", "StroboPlus HD"]
    assert devices["StroboStomp HD"] == "guitar_pedal"
    assert devices["StroboClip HD"] == "other"


@pytest.mark.asyncio
async def test_peterson_keeps_the_databases_spelling_of_stroboplus():
    """Peterson writes StroboPLUS where the database has StroboPlus HD.

    Unmapped, the listing creates a second row and orphans the tracked one.
    """
    scraper = _scraper_on(PETERSON_HISTORY)

    names = [d.name for d in (await scraper.fetch_device_list()).devices]
    assert "StroboPlus HD" in names and "StroboPLUS HD" not in names

    result = await scraper.fetch_firmware_versions("StroboPlus HD", scraper.SUPPORT_URL)
    assert [f.version for f in result.firmware_versions] == ["1.1.12"]


def test_peterson_keeps_stroboclip_hd_and_hdc_apart():
    """HD runs 1.0.1-1.0.6 and HDC runs 1.0.07-1.0.15, per Peterson's own data.

    The old scraper conflated them, leaving ten of HDC's versions on HD -- including
    the one marked latest, so the dashboard showed a version HD never had.
    """
    from src.scrapers.plugins.peterson import PetersonScraper

    history = PetersonScraper()._parse_history(PETERSON_HISTORY)

    assert [f.version for f in history["StroboClip HD"]] == ["1.0.6"]
    assert [f.version for f in history["StroboClip HDC"]] == ["1.0.15"]


@pytest.mark.asyncio
async def test_peterson_orders_releases_numerically():
    """1.0.10 outranks 1.0.9, which comparing the strings reverses."""
    html = '<div class="firmwareResults">' + "".join(
        _entry("StroboClip HDC", version, "Monday, April 1, 2024 9:00:00 AM EDT", [], "{}")
        for version in ("1.0.9", "1.0.10", "1.0.07")
    ) + "</div>"
    scraper = _scraper_on(html)

    result = await scraper.fetch_firmware_versions("StroboClip HDC", scraper.SUPPORT_URL)

    assert [f.version for f in result.firmware_versions] == ["1.0.10", "1.0.9", "1.0.07"]


@pytest.mark.asyncio
async def test_peterson_fails_loudly_when_the_history_is_missing():
    unreachable = _scraper_on(None)
    assert (await unreachable.fetch_device_list()).success is False

    rearranged = _scraper_on("<div>Firmware history coming soon</div>")
    assert (await rearranged.fetch_device_list()).success is False
    assert (await rearranged.fetch_firmware_versions("StroboStomp HD", rearranged.SUPPORT_URL)).success is False


@pytest.mark.asyncio
async def test_peterson_reports_no_firmware_for_a_catalogued_tuner_the_history_omits():
    """StroboRack and Body Beat Sync take no firmware; their rows predate discovery."""
    scraper = _scraper_on(PETERSON_HISTORY)

    result = await scraper.fetch_firmware_versions("StroboRack", scraper.SUPPORT_URL)

    assert result.success is True
    assert result.firmware_versions == []
