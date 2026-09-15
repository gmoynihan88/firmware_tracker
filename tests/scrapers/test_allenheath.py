import pytest


# SQ and SQ+ style: the version in an h3, the month on its own line beneath, and older
# releases that open straight into their notes with no date.
SQ_BODY = """
<h2>Current Version</h2>
<h3><strong>V1.6.3</strong> Maintenance release</h3>
<h4>February 2026</h4>
<h3><strong>Issues fixed:</strong></h3>
<ul><li>ID-2358: Failure to automatically update firmware of some expanders</li></ul>
<h2>Previous Versions</h2>
<h3><strong>V1.6.2</strong> Maintenance release</h3>
<p>SQ-Drive:</p>
<ul><li>Support for AR/AB hardware following component changes</li></ul>
<p>March 2024</p>
<h3><strong>V1.5.11</strong> Maintenance release</h3>
<p>June 2025</p>
<ul><li>Fixed issue where Parallel Path values were not displayed</li></ul>
"""

# dLive, GLD, ME-U and Avantis: version and month in one h2, with non-breaking spaces,
# under a note that quotes a version in prose.
AVANTIS_BODY = """
<p>ⓘ Downgrading <strong>from</strong> V1.31 or later <strong>to</strong> V1.30 or earlier will cause user profiles to reset.</p>
<h1>Current Version Release Notes</h1>
<h2>V2.01 - Maintenance Release. May 2026</h2>
<h3>Fixes</h3>
<p>ID4380 - On some units, 2 or more of the RackUltra FX slots could fail</p>
<h1>Previous Version Release Notes</h1>
<h2>V1.34 - Maintenance Release. November 2025</h2>
<p>ID3417 Using a Softkey to recall a scene</p>
"""

# The Dante cards: "V1.0.0 - Feb 2023", the month abbreviated.
DANTE_BODY = """
<h3>V1.0.4 - February 2026</h3><p>Maintenance release.</p>
<h3>V1.0.0 - Feb 2023</h3><p>This was the first release.</p>
"""

ML_BODY = "<p>Being 'firmware' rather than computer software, there weren't ever any officially published release notes for ML software version V1.40.</p>"


def _article(aid, title, body):
    return {"id": aid, "title": title, "body": body,
            "html_url": f"https://support.allen-heath.com/hc/en-gb/articles/{aid}"}


ARTICLES = [
    _article(1, "SQ Firmware Release Notes", SQ_BODY),
    _article(2, "Avantis Firmware Release Notes", AVANTIS_BODY),
    _article(3, "Dante V3 Option Card Firmware Release Notes", DANTE_BODY),
    _article(4, "ML. Firmware V1.40 Release Notes", ML_BODY),
    _article(5, "dLive Firmware Release Notes - Firmware Version 2.12",
             "<h2>Version 2.12 - Maintenance Release. January 2026</h2><h3>Fixes</h3>"),
    _article(6, "GLD Release Notes – Firmware Version 1.63",
             "<h2>Version 1.63 - Maintenance Release. November 2025</h2>"),
    # The control app's history: not firmware.
    _article(7, "DT Preamp Control Release Notes", "<h3>V1.21 Maintenance release - June 2026</h3>"),
    _article(8, "SQ+ Firmware Update Instructions", "<p>Download V2.0.3 and copy it to a USB drive.</p>"),
]


def _scraper(pages=None):
    from src.scrapers.plugins.allenheath import AllenHeathScraper

    scraper = AllenHeathScraper()
    first = AllenHeathScraper.ARTICLES_URL
    second = first + "&page=2"
    pages = pages if pages is not None else {
        first: {"articles": ARTICLES[:4], "next_page": second},
        second: {"articles": ARTICLES[4:], "next_page": None},
    }
    fetched = []

    async def _json(url, *_args, **_kwargs):
        fetched.append(url)
        return pages.get(url)

    scraper.fetch_json = _json
    return scraper, fetched


def _parse(body):
    from src.scrapers.plugins.allenheath import AllenHeathScraper

    return AllenHeathScraper()._parse_article(body)


def test_allenheath_reads_a_month_on_the_line_below_the_version():
    versions = {fw.version: fw for fw in _parse(SQ_BODY)}

    assert list(versions) == ["1.6.3", "1.6.2", "1.5.11"]
    assert versions["1.6.3"].release_date.strftime("%Y-%m-%d") == "2026-02-01"
    assert versions["1.5.11"].release_date.strftime("%Y-%m-%d") == "2025-06-01"
    assert "ID-2358" in versions["1.6.3"].changelog


def test_allenheath_leaves_a_release_undated_rather_than_borrowing_a_date():
    """SQ's V1.6.2 opens with "SQ-Drive:", and the next month belongs to V1.5.11."""
    versions = {fw.version: fw for fw in _parse(SQ_BODY)}

    assert versions["1.6.2"].release_date is None
    assert "June 2025" not in (versions["1.6.2"].changelog or "")
    # A month standing alone among the notes is a note, not this release's date.
    assert "March 2024" in versions["1.6.2"].changelog


def test_allenheath_reads_the_month_inside_the_heading_and_ignores_prose_versions():
    versions = _parse(AVANTIS_BODY)

    assert [fw.version for fw in versions] == ["2.01", "1.34"]
    assert [fw.release_date.strftime("%Y-%m") for fw in versions] == ["2026-05", "2025-11"]


def test_allenheath_reads_an_abbreviated_month():
    versions = {fw.version: fw.release_date.strftime("%Y-%m") for fw in _parse(DANTE_BODY)}

    assert versions == {"1.0.4": "2026-02", "1.0.0": "2023-02"}


def test_allenheath_names_products_from_each_title_shape():
    from src.scrapers.plugins.allenheath import AllenHeathScraper

    product = AllenHeathScraper()._product
    assert product("SQ Firmware Release Notes") == ("SQ", None)
    assert product("dLive Firmware Release Notes - Firmware Version 2.12") == ("dLive", None)
    assert product("GLD Release Notes – Firmware Version 1.63") == ("GLD", None)
    assert product("ML. Firmware V1.40 Release Notes") == ("ML", "1.40")
    assert product("Qu-5/6/7 Firmware Release Notes") == ("Qu-5/6/7", None)
    assert product("DT Preamp Control Release Notes") is None
    assert product("SQ+ Firmware Update Instructions") is None


@pytest.mark.asyncio
async def test_allenheath_lists_every_family_with_firmware_release_notes():
    scraper, fetched = _scraper()

    devices = {d.name: d for d in (await scraper.fetch_device_list()).devices}

    assert set(devices) == {"SQ", "Avantis", "Dante V3 Option Card", "ML", "dLive", "GLD"}
    assert devices["SQ"].firmware_page_url == "https://support.allen-heath.com/hc/en-gb/articles/1"
    assert len(fetched) == 2, "followed next_page"

    ml = await scraper.fetch_firmware_versions("ML", devices["ML"].firmware_page_url)
    assert [(fw.version, fw.release_date) for fw in ml.firmware_versions] == [("1.40", None)]


@pytest.mark.asyncio
async def test_allenheath_reads_the_help_centre_once_per_scrape():
    scraper, fetched = _scraper()

    listing = await scraper.fetch_device_list()
    for device in listing.devices:
        await scraper.fetch_firmware_versions(device.name, device.firmware_page_url)

    assert len(fetched) == 2


@pytest.mark.asyncio
async def test_allenheath_fails_loudly():
    from src.scrapers.plugins.allenheath import AllenHeathScraper

    first = AllenHeathScraper.ARTICLES_URL
    broken_page = _scraper({first: {"articles": ARTICLES[:4], "next_page": first + "&page=2"}})[0]
    assert (await broken_page.fetch_device_list()).success is False

    nothing = _scraper({first: {"articles": [ARTICLES[6], ARTICLES[7]], "next_page": None}})[0]
    assert (await nothing.fetch_device_list()).success is False

    scraper, _ = _scraper()
    missing = await scraper.fetch_firmware_versions("iLive", "")
    assert missing.success is False


def test_allenheath_does_not_take_a_paragraph_that_opens_with_a_version_as_a_release():
    """GLD's article opens "V1.63 is a maintenance release of GLD Firmware." above the
    heading that dates it; read as a release, it would claim 1.63 first, undated."""
    body = (
        "<p>V1.63 is a maintenance release of GLD Firmware.</p>"
        "<h2>Version 1.63 - Maintenance Release. November 2025</h2><p>ID1 fix</p>"
    )

    versions = _parse(body)

    assert [(fw.version, fw.release_date.strftime("%Y-%m")) for fw in versions] == [("1.63", "2025-11")]


def test_allenheath_orders_versions_numerically():
    """1.10 is newer than 1.9, which comparing the text gets backwards."""
    body = "<h3>V1.9 - April 2019</h3><p>a</p><h3>V1.10 - May 2020</h3><p>b</p>"

    assert [fw.version for fw in _parse(body)] == ["1.10", "1.9"]


# As served for Avantis: section headings below the version, notes in bare paragraphs
# and in divs, words split across spans, non-breaking-space spacers.
AVANTIS_LIVE = """<hr><h1 id="h_1">Current Version Release Notes</h1><h2 id="h_2">V2.01 - Maintenance Release. May 2026</h2><h3 class="wysiwyg-text-align-justify" id="h_3">Fixes</h3><p class="wysiwyg-text-align-justify">ID4380 - On some units, 2 or more of the RackUltra FX slots could sometimes fail to pass audio at first boot or subsequent boots.</p><p class="wysiwyg-text-align-justify">ID4277 - Fixed some instances of UI crash at shutdown.</p><p class="wysiwyg-text-align-justify"> </p><h3 class="wysiwyg-text-align-justify" id="h_4">Known Issues</h3><div><p><span data-ogsc="black">ID3150 - Pinch control of PEQ bandwidth does not work reliably on macOS.</span></p></div><div>
<p><span data-ogsc="black">ID2306 - MIDI Softkeys in Director send both their ‘on press’ and ‘on</span><span data-ogsc="black"> </span><span data-ogsc="black" data-markjs="true">release</span><span data-ogsc="black">’ events on press.</span></p>
</div><div><p> </p></div><hr><h1 class="wysiwyg-text-align-justify" id="h_5">Previous Version Release Notes</h1><h2 id="h_6">V2.0 - Feature Release. April 2026</h2><div>
<h3 id="h_7">New dPack Features*</h3>
<ul>
<li data-list-item-id="e5a3">
<span data-ogsc="black">Increased</span><span data-ogsc="black"> channel count to 96 input channels</span></li>
<li data-list-item-id="e5a4">Added CompStortion DEEP compressor model</li>
</ul></div>"""


def test_allenheath_keeps_each_note_on_its_own_line():
    """The notes were one run-on line, and cut at 500 characters."""
    versions = {fw.version: fw for fw in _parse(AVANTIS_LIVE)}

    assert versions["2.01"].changelog == (
        "Fixes\n"
        "ID4380 - On some units, 2 or more of the RackUltra FX slots could sometimes fail to pass audio at first boot or subsequent boots.\n"
        "ID4277 - Fixed some instances of UI crash at shutdown.\n"
        "Known Issues\n"
        "ID3150 - Pinch control of PEQ bandwidth does not work reliably on macOS.\n"
        "ID2306 - MIDI Softkeys in Director send both their ‘on press’ and ‘on release’ events on press."
    )
    # "Previous Version Release Notes" is the article's heading, not a note.
    assert versions["2.0"].changelog == (
        "New dPack Features*\n"
        "- Increased channel count to 96 input channels\n"
        "- Added CompStortion DEEP compressor model"
    )
    assert versions["2.01"].release_date.strftime("%Y-%m") == "2026-05"


def test_allenheath_leaves_the_article_s_sections_and_the_date_out_of_the_notes():
    """SQ puts versions in h3 under h2 "Previous Versions", and the month in an h4."""
    versions = {fw.version: fw for fw in _parse(SQ_BODY)}

    assert versions["1.6.3"].changelog == "- ID-2358: Failure to automatically update firmware of some expanders"
    assert versions["1.6.3"].release_date.strftime("%Y-%m") == "2026-02"
    assert versions["1.6.2"].changelog == (
        "SQ-Drive:\n- Support for AR/AB hardware following component changes\nMarch 2024"
    )
