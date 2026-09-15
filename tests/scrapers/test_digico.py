import pytest

UPLOADS = "https://digico.biz/wp-content/uploads"


def _link(label, href):
    return f'<span class="download-link" data-link="{href}">{label}</span>'


# As served: the date, the download buttons, then sections. V22 names only the major
# in its title; its builds are section headings.
V22_QUANTUM = (
    '<p>Release Date: June 2026</p><h2 id="h_1">Download Links</h2><p>'
    + _link("Quantum 112", f"{UPLOADS}/2026/06/Quantum1_V2242z_Update_Package.zip") + " "
    + _link("Quantum 7", f"{UPLOADS}/2026/06/Quantum7_V2242z_Update_Package.zip") + " \xa0"
    + _link("Quantum 852", "https://we.tl/t-nXvLOvQczVfuokVT")
    + '</p><p><span style="color: #C72809;"><span data-teams="true">Please Note: The links above for the Q225 &amp; Q225 DS are console specific.</span></span></p>'
    '<p>\xa0</p><h3 id="h_2">Key New Features</h3><ul>\n'
    '<li data-list-item-id="e0e8">Setlists – Smarter Snapshot Control</li>\n</ul>'
    '<h3 id="h_3">v2242 Errors Fixed</h3><ul>\n<li>Q852 improved snapshot recall performance when using crossfades.</li>\n</ul><p>\xa0</p>'
    '<h3 id="h_4">v2232 Errors Fixed</h3><ul>\n<li>Console was intermittently sending wrong mapping information to Klang</li>\n</ul>'
)

SD_V2025 = (
    '<p>Release Date: Nov 2024</p>\n<h2 id="h_1" style="box-sizing: border-box;">Download Links</h2><p>'
    + _link(" SD12", f"{UPLOADS}/2025/03/SD12_V2025_Update_Package.zip")
    + '</p><h3>Errors Fixed</h3><ul><li>Fixed an SD fault.</li></ul>'
)

QUANTUM_V2025 = (
    '<p>Release Date: March 2025</p>\n<h2 id="h_1"><strong><span class="fontstyle0">Download Links</span></strong></h2><p>'
    + _link(" Quantum 225", f"{UPLOADS}/2025/03/Quantum2_V2025z_Update_Package-1.zip") + " "
    + _link(" Quantum 852", "https://we.tl/t-example")
    + '</p><h3>Errors Fixed</h3><ul><li>Fixed a Quantum fault.</li></ul>'
)

# Split by the editor: the month sits in a span of its own.
SD_V1742 = (
    '<p>Release Date: <span class="fontstyle0">April 2024</span></p>\n'
    '<h2 id="h_1"><strong><span class="fontstyle0">Download Links</span></strong></h2>\n<p>'
    + _link(" SD12", f"{UPLOADS}/2024/04/SD12_V1742_Update_Package.zip")
    + '</p><h3>Key Feature Changes</h3><ul><li>Pulse software for Quantum 338 and Quantum 225</li></ul>'
)

QUANTUM_852_V1889 = (
    '<p>' + _link(" Download Software", "https://we.tl/t-DkGXTxARyg") + '</p>\n'
    '<h3 id="h_1">New Features and improvements in Quantum8 since V1879.</h3>\n<ul>\n'
    '<li>Master screen menu bar has been repositioned to the lower part of the screen.</li>\n</ul>'
)

S_SERIES_V311 = (
    '<p>Release Date: October 2025</p><p>'
    + _link("S21", f"{UPLOADS}/2025/10/S21_V3.1.1_Web_Updater-1.zip") + " "
    + _link("S31", f"{UPLOADS}/2025/10/S31_V3.1.1_Web_Updater-1.zip")
    + '</p><h3 id="h_1">Issues Fixed</h3><ul>\n<li data-list-item-id="ee4a"><span class="fontstyle0">Prevented issues when removing external USB device when loading or saving sessions.</span></li>\n</ul>'
)

S21_V261 = '<p>' + _link(" S21 Console Software V2.6.1", f"{UPLOADS}/2020/06/S21_V2_6_1_Web_Updater.zip") + '</p>'
S31_V261 = '<p>' + _link(" S31 Console Software V2.6.1", f"{UPLOADS}/2020/06/S31_V2_6_1_Web_Updater.zip") + '</p>'


def _article(aid, title, body):
    return {"id": aid, "title": title, "body": body,
            "html_url": f"https://support.digico.biz/hc/en-gb/articles/{aid}"}


ARTICLES = [
    _article(1, "V22 Quantum Console Software", V22_QUANTUM),
    _article(2, "V22 Quantum Offline Software", V22_QUANTUM),
    _article(3, "SD Console Software V2025", SD_V2025),
    _article(4, "Quantum Console Software V2025", QUANTUM_V2025),
    _article(5, "SD Console Software Version V1742", SD_V1742),
    _article(6, "Quantum 852 Console Software V1889", QUANTUM_852_V1889),
    _article(7, "S-Series Console Software V3.1.1", S_SERIES_V311),
    _article(8, "S21 Console Software V2.6.1", S21_V261),
    _article(9, "S31 Console Software V2.6.1", S31_V261),
    _article(10, "I want to roll back the current console software version to an earlier version.", "<p>Contact support.</p>"),
    _article(11, "DMI-Dante64@96 with IP Zynq HC – Upgrading firmware to v4.2.11", "<p>Firmware v4.2.11</p>"),
]


def _scraper(pages=None):
    from src.scrapers.plugins.digico import DigicoScraper

    first = DigicoScraper.ARTICLES_URL
    second = first + "&page=2"
    pages = pages if pages is not None else {
        first: {"articles": ARTICLES[:5], "next_page": second},
        second: {"articles": ARTICLES[5:], "next_page": None},
    }
    scraper = DigicoScraper()
    fetched = []

    async def _json(url, *_args, **_kwargs):
        fetched.append(url)
        return pages.get(url)

    scraper.fetch_json = _json
    return scraper, fetched


async def _versions(scraper, device):
    result = await scraper.fetch_firmware_versions(device, "")
    assert result.success, result.error
    return {fw.version: fw for fw in result.firmware_versions}


@pytest.mark.asyncio
async def test_digico_lists_each_software_line_and_leaves_out_the_offline_editors():
    scraper, _ = _scraper()

    listing = await scraper.fetch_device_list()

    assert listing.success is True
    assert sorted(d.name for d in listing.devices) == ["Quantum 852", "Quantum Range", "S-Series", "SD Range"]
    quantum = await _versions(scraper, "Quantum Range")
    # V22 Quantum Offline Software carries the same builds and is not read twice as
    # console software; the Dante card firmware is not a console at all.
    assert list(quantum) == ["2242", "2232", "2025"]
    pages = {d.name: d.firmware_page_url for d in listing.devices}
    assert pages["Quantum Range"].endswith("/1"), "linked the offline editor's article"


@pytest.mark.asyncio
async def test_digico_reads_the_builds_under_a_major_only_title():
    """"V22 Quantum Console Software" holds v2242 and v2232; only the newest is dated."""
    scraper, _ = _scraper()

    quantum = await _versions(scraper, "Quantum Range")

    assert quantum["2242"].release_date.strftime("%Y-%m") == "2026-06"
    assert quantum["2232"].release_date is None
    assert quantum["2242"].changelog == (
        "Key New Features\n- Setlists – Smarter Snapshot Control\n"
        "v2242 Errors Fixed\n- Q852 improved snapshot recall performance when using crossfades."
    )
    assert quantum["2232"].changelog == (
        "v2232 Errors Fixed\n- Console was intermittently sending wrong mapping information to Klang"
    )


@pytest.mark.asyncio
async def test_digico_leaves_a_version_undated_when_its_articles_disagree():
    """SD V2025 says Nov 2024, V1926's date; Quantum V2025 says March 2025."""
    scraper, _ = _scraper()

    sd = await _versions(scraper, "SD Range")
    quantum = await _versions(scraper, "Quantum Range")

    assert sd["2025"].release_date is None
    assert quantum["2025"].release_date is None
    # A date split across the editor's spans is still read.
    assert sd["1742"].release_date.strftime("%Y-%m") == "2024-04"


@pytest.mark.asyncio
async def test_digico_gives_quantum_852_its_own_builds_and_the_quantum_releases_that_list_it():
    scraper, _ = _scraper()

    q852 = await _versions(scraper, "Quantum 852")

    assert list(q852) == ["2242", "2232", "2025", "1889"]
    assert q852["1889"].release_date is None
    assert q852["1889"].changelog.startswith("New Features and improvements in Quantum8 since V1879.")


@pytest.mark.asyncio
async def test_digico_merges_s21_and_s31_into_the_s_series():
    scraper, _ = _scraper()

    s_series = await _versions(scraper, "S-Series")

    assert list(s_series) == ["3.1.1", "2.6.1"]
    assert s_series["3.1.1"].release_date.strftime("%Y-%m") == "2025-10"
    # Notes start at the first section: the date and the download buttons are not notes.
    assert s_series["3.1.1"].changelog == (
        "Issues Fixed\n- Prevented issues when removing external USB device when loading or saving sessions."
    )
    assert s_series["2.6.1"].changelog is None


@pytest.mark.asyncio
async def test_digico_orders_versions_numerically():
    scraper, _ = _scraper({
        _scraper()[0].ARTICLES_URL: {"articles": [
            _article(1, "S-Series Console Software V3.0.9", "<p>Release Date: June 2022</p>"),
            _article(2, "S-Series Console Software V3.0.15", "<p>Release Date: November 2022</p>"),
            _article(3, "S-Series Console Software V3.1.1", S_SERIES_V311),
        ], "next_page": None},
    })

    s_series = await _versions(scraper, "S-Series")

    # 3.0.15 is newer than 3.0.9, which comparing the text reverses.
    assert list(s_series) == ["3.1.1", "3.0.15", "3.0.9"]


@pytest.mark.asyncio
async def test_digico_reads_the_help_centre_once_per_scrape():
    scraper, fetched = _scraper()

    listing = await scraper.fetch_device_list()
    for device in listing.devices:
        await scraper.fetch_firmware_versions(device.name, device.firmware_page_url)

    assert len(fetched) == 2


@pytest.mark.asyncio
async def test_digico_fails_loudly():
    from src.scrapers.plugins.digico import DigicoScraper

    assert (await _scraper({})[0].fetch_device_list()).success is False
    second = {DigicoScraper.ARTICLES_URL: {"articles": ARTICLES[:5], "next_page": DigicoScraper.ARTICLES_URL + "&page=2"}}
    assert (await _scraper(second)[0].fetch_device_list()).success is False
    none = {DigicoScraper.ARTICLES_URL: {"articles": ARTICLES[9:], "next_page": None}}
    assert (await _scraper(none)[0].fetch_device_list()).success is False

    scraper, _ = _scraper()
    assert (await scraper.fetch_firmware_versions("SD12", "")).success is False
