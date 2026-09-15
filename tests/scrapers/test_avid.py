import pytest

from tests.support import _stub_fetch


def _avid_entry(heading, body):
    """One entry as the page writes it: the heading alone in a div, its notes in the next."""
    return f'<div class=""><h2 class="mb-6">{heading}</h2></div><div><div class="rte intro-text">{body}</div></div>'


AVID_WHATS_NEW = "<html><body><main><div><h1>What's new in Pro Tools</h1>" + "".join([
    _avid_entry("PRO TOOLS 2026.4.1 (JULY 2026)",
                '<a href="/resource-center/x">Avid Pro Tools 2026.4.1</a> is now available, bringing support for M5 Macs.<br/><br/>'),
    _avid_entry("PRO TOOLS 2026.4 (APRIL 2026)",
                "<p>Pro Tools 2026.4 introduces Track Pin.</p><h3>Faster editing and navigation with Track Pin</h3>"
                "<ul><li><p>Pin a track in place.</p></li></ul>"),
    _avid_entry("FORTE FOR PRO TOOLS (JUNE 2025)", "<p>A third-party instrument host.</p>"),
    _avid_entry("UVI FALCON FOR PRO TOOLS 2024.10 (OCTOBER 2024)", "<p>A third-party instrument, versioned for Pro Tools.</p>"),
    _avid_entry("K-Devices TATAT MIDI Plugin (April 2025)", "<p>A third-party MIDI plug-in.</p>"),
    _avid_entry("PRO TOOLS 2023.3 (MARCH 2023)", "<p>Native Apple silicon support.</p>"),
]) + "</div></main><footer><p>Copyright Avid</p></footer></body></html>"


def test_pro_tools_reads_only_pro_tools_release_headings():
    """Third-party announcements share the list: "UVI FALCON FOR PRO TOOLS 2024.10" is not a release."""
    from src.scrapers.plugins.avid import AvidScraper

    versions = AvidScraper()._parse_whats_new(AVID_WHATS_NEW)

    assert [fw.version for fw in versions] == ["2026.4.1", "2026.4", "2023.3"]


def test_pro_tools_dates_a_release_by_its_heading_month_not_its_version():
    """2026.4.1 patches April's release but shipped in July; the day is not published."""
    from src.scrapers.plugins.avid import AvidScraper

    versions = AvidScraper()._parse_whats_new(AVID_WHATS_NEW)

    assert [(fw.version, fw.release_date.date().isoformat()) for fw in versions] == [
        ("2026.4.1", "2026-07-01"), ("2026.4", "2026-04-01"), ("2023.3", "2023-03-01"),
    ]


def test_pro_tools_notes_are_the_block_after_the_heading_up_to_the_next():
    """Each heading sits alone in a wrapper div, so its notes are not its siblings."""
    from src.scrapers.plugins.avid import AvidScraper

    versions = {fw.version: fw for fw in AvidScraper()._parse_whats_new(AVID_WHATS_NEW)}

    assert versions["2026.4"].changelog.splitlines() == [
        "Pro Tools 2026.4 introduces Track Pin.", "Faster editing and navigation with Track Pin", "Pin a track in place.",
    ]
    assert versions["2026.4.1"].changelog == "Avid Pro Tools 2026.4.1 is now available, bringing support for M5 Macs."
    assert versions["2023.3"].changelog == "Native Apple silicon support."


@pytest.mark.asyncio
async def test_pro_tools_is_one_device_from_one_fetch():
    from src.scrapers.plugins.avid import AvidScraper as A

    scraper = A()
    asked = _stub_fetch(scraper, {A.WHATS_NEW_URL: AVID_WHATS_NEW})

    devices = (await scraper.fetch_device_list()).devices
    result = await scraper.fetch_firmware_versions(devices[0].name, devices[0].firmware_page_url)

    assert asked == [A.WHATS_NEW_URL]
    assert [(d.name, d.category) for d in devices] == [("Pro Tools", "vst_plugin")]
    assert result.firmware_versions[0].version == "2026.4.1"


@pytest.mark.asyncio
async def test_pro_tools_fails_loudly_without_the_page():
    from src.scrapers.plugins.avid import AvidScraper as A

    scraper = A()
    _stub_fetch(scraper, {})

    assert (await scraper.fetch_device_list()).success is False
