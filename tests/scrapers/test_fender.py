import json

import pytest


def _fender_article() -> str:
    """One release block, with everything that surrounds the real version."""
    return """
    <p>Tone Master Pro Firmware - v1.8.58</p>
    <p>Download the latest firmware here:</p>
    <p>Tone Master Pro Firmware – v1.8.58 download link</p>
    <p>Pro Control App and Windows ASIO Driver</p>
    <p>Mac – v1.8.4.9728 download link</p>
    <p>PC – v1.8.4.9733 download link</p>
    <p>Fender Universal ASIO Driver download link (Windows) - v5.72.0 (updated 3/26/2025)</p>
    <p>macOS Monterey 12.7 or later</p>
    <p>Release Notes:</p>
    <p>Version Information 12/3/2025</p>
    <p>Tone Master Pro Firmware – v1.7.53 download link</p>
    <p>Fender Universal ASIO Driver download link (Windows) - v5.72.0 (updated 3/26/2025)</p>
    <p>Version Information 8/27/2025</p>
    <p>Tone Master Pro Firmware – v1.6.48 download link</p>
    """


def test_fender_pairs_a_version_with_the_date_above_it():
    from src.scrapers.plugins.fender import FenderScraper

    parsed = FenderScraper()._parse_article(_fender_article())
    versions = parsed["Tone Master Pro"]

    assert [v for v, _ in versions] == ["1.8.58", "1.7.53", "1.6.48"]
    assert versions[1][1].strftime("%Y-%m-%d") == "2025-12-03"
    assert versions[2][1].strftime("%Y-%m-%d") == "2025-08-27"


def test_fender_leaves_the_newest_undated_rather_than_borrowing():
    """A download line with no Version Information above it stays undated.

    The next date down belongs to v1.7.53, five releases earlier. The live article
    has since given its newest releases dated blocks of their own; this guards the
    case where a release has none.
    """
    from src.scrapers.plugins.fender import FenderScraper

    versions = FenderScraper()._parse_article(_fender_article())["Tone Master Pro"]

    assert versions[0][0] == "1.8.58"
    assert versions[0][1] is None


def test_fender_ignores_the_control_app_and_the_asio_driver():
    """Mac, PC and the driver all state versions within four lines of the firmware.

    The driver is the worst of them: "updated 3/26/2025" repeats inside every
    release block, so a date search finds it thirteen times in the real article and
    would stamp most of the history with one driver's date.
    """
    from src.scrapers.plugins.fender import FenderScraper

    parsed = FenderScraper()._parse_article(_fender_article())
    found = {v for entries in parsed.values() for v, _ in entries}

    assert "1.8.4.9728" not in found, "took the Pro Control app for Mac"
    assert "1.8.4.9733" not in found, "took the Pro Control app for Windows"
    assert "5.72.0" not in found, "took the ASIO driver"
    assert set(parsed) == {"Tone Master Pro"}
    assert all(d is None or d.year != 2025 or d.month != 3 for _, d in parsed["Tone Master Pro"])


def test_fender_skips_the_summary_line_without_a_download():
    """The article repeats the current version at the top with no download link.

    Counting it would double the newest release rather than add one.
    """
    from src.scrapers.plugins.fender import FenderScraper

    versions = FenderScraper()._parse_article(_fender_article())["Tone Master Pro"]

    assert [v for v, _ in versions].count("1.8.58") == 1


@pytest.mark.asyncio
async def test_fender_fails_when_the_zendesk_api_is_unreachable():
    """An empty device list would read as a vendor that publishes nothing —
    which is exactly what the Cloudflare-blocked website already suggests."""
    import json

    from src.scrapers.plugins.fender import FenderScraper

    scraper = FenderScraper()

    async def no_response(url, **kwargs):
        return None

    scraper.fetch_page = no_response
    assert (await scraper.fetch_device_list()).success is False

    empty = FenderScraper()

    async def no_articles(url, **kwargs):
        return json.dumps({"articles": [], "next_page": None})

    empty.fetch_page = no_articles
    assert (await empty.fetch_device_list()).success is False


def _fender_scraper(pages):
    """A scraper serving canned Zendesk pages, keyed by page number."""
    import json

    from src.scrapers.plugins.fender import FenderScraper

    scraper = FenderScraper()
    asked = []

    async def fake_fetch(url, **kwargs):
        asked.append(url)
        page = int(url.rsplit("page=", 1)[1])
        body = pages.get(page)
        return json.dumps(body) if body is not None else None

    scraper.fetch_page = fake_fetch
    return scraper, asked


@pytest.mark.asyncio
async def test_fender_reads_every_page_of_articles():
    """Zendesk paginates, and the firmware articles are not all on page one."""
    pages = {
        1: {"articles": [{"body": _fender_article()}], "next_page": "page=2"},
        2: {"articles": [{"body": "<p>Tone Master Twin Firmware – v2.0.42 download link</p>"}],
            "next_page": None},
    }
    scraper, asked = _fender_scraper(pages)
    devices = await scraper.fetch_device_list()

    assert [d.name for d in devices.devices] == ["Tone Master Pro", "Tone Master Twin"]
    assert len(asked) == 2


@pytest.mark.asyncio
async def test_fender_keeps_a_date_when_a_later_article_repeats_the_version():
    """Older articles restate the current release without its date.

    Taking the last sighting would drop a date the first article supplied.
    """
    pages = {
        1: {"articles": [
                {"body": "<p>Version Information 12/3/2025</p>"
                         "<p>Tone Master Twin Firmware – v2.0.42 download link</p>"},
                {"body": "<p>Tone Master Twin Firmware – v2.0.42 download link</p>"},
            ], "next_page": None},
    }
    scraper, _ = _fender_scraper(pages)
    result = await scraper.fetch_firmware_versions("Tone Master Twin", "")

    assert len(result.firmware_versions) == 1
    assert result.firmware_versions[0].release_date.strftime("%Y-%m-%d") == "2025-12-03"


@pytest.mark.asyncio
async def test_fender_reads_the_api_once_for_the_whole_catalogue():
    pages = {1: {"articles": [{"body": _fender_article()}], "next_page": None}}
    scraper, asked = _fender_scraper(pages)

    await scraper.fetch_device_list()
    await scraper.fetch_firmware_versions("Tone Master Pro", "")

    assert len(asked) == 1


@pytest.mark.asyncio
async def test_fender_reports_a_retired_product_as_an_absence():
    pages = {1: {"articles": [{"body": _fender_article()}], "next_page": None}}
    scraper, _ = _fender_scraper(pages)
    result = await scraper.fetch_firmware_versions("Tone Master Retired", "")

    assert result.success is True
    assert result.firmware_versions == []


FENDER_SPLIT_DATES = """
<p>Version Information</p>
<p>15 Jul 2026</p>
<p>Tone Master Pro Firmware - v1.8.58</p>
<p>Download the latest firmware here:</p>
<p>Tone Master Pro Firmware – v1.8.58 download link</p>
<p>--------------------------------</p>
<p>Version Information</p>
<p>6/25/2025</p>
<p>Tone Master Pro Firmware – v1.8.45 download link</p>
<p>Version Information 12/3/2025</p>
<p>Tone Master Pro Firmware – v1.7.53 download link</p>
<p>Version Information</p>
<p>Tone Master Pro Firmware – v1.0.0 download link</p>
"""


def test_fender_reads_a_date_on_the_line_after_version_information():
    """The newest releases put the date on its own line, in either of two forms.

    A bare "Version Information" followed by something that is not a date leaves
    that release undated -- and the line after it must still be read.
    """
    from src.scrapers.plugins.fender import FenderScraper

    versions = FenderScraper()._parse_article(FENDER_SPLIT_DATES)["Tone Master Pro"]

    assert [(v, d.date().isoformat() if d else None) for v, d in versions] == [
        ("1.8.58", "2026-07-15"),
        ("1.8.45", "2025-06-25"),
        ("1.7.53", "2025-12-03"),
        ("1.0.0", None),
    ]


FENDER_SIBLINGS = """
<p>Version Information 7/14/2026</p>
<p>Tone Master Twin Firmware – v2.0.42 download link</p>
<p>Firmware update for Tone Master Twin Reverbs using Jensen N12K speakers.</p>
<p>Tone Master Twin Blonde Firmware – v2.0.42 download link</p>
<p>Firmware update for Tone Master Twin Reverbs using Celestion G12 NEO Creamback speakers.</p>
<p>Tone Master Twin Firmware – v2.0.41 download link</p>
"""


def test_fender_gives_sibling_models_the_date_of_their_shared_release():
    """Twin and Twin Blonde ship one firmware under one date; both take it.

    Twin listed a second time in the same block is another release, so it does not.
    """
    from src.scrapers.plugins.fender import FenderScraper

    parsed = FenderScraper()._parse_article(FENDER_SIBLINGS)
    as_text = {name: [(v, d.date().isoformat() if d else None) for v, d in vals]
               for name, vals in parsed.items()}

    assert as_text == {
        "Tone Master Twin": [("2.0.42", "2026-07-14"), ("2.0.41", None)],
        "Tone Master Twin Blonde": [("2.0.42", "2026-07-14")],
    }
