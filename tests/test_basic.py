import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from httpx import AsyncClient, ASGITransport

from src.database import Base, get_db
from src.main import app

# Use an in-memory SQLite database for tests so the production DB is never touched
test_engine = create_async_engine("sqlite+aiosqlite://", echo=False)
test_session_maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def override_get_db():
    async with test_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
async def setup_db():
    """Set up test database."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client():
    """Create test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_dashboard(client):
    """Test dashboard loads."""
    response = await client.get("/")
    assert response.status_code == 200
    assert "Firmware Tracker" in response.text


@pytest.mark.asyncio
async def test_catalog(client):
    """Test catalog page loads."""
    response = await client.get("/catalog")
    assert response.status_code == 200
    assert "Device Catalog" in response.text


@pytest.mark.asyncio
async def test_notifications(client):
    """Test notifications page loads."""
    response = await client.get("/notifications")
    assert response.status_code == 200
    assert "Notifications" in response.text


@pytest.mark.asyncio
async def test_api_manufacturers(client):
    """Test manufacturers API endpoint."""
    response = await client.get("/api/manufacturers")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_api_scrapers(client):
    """Test scrapers list endpoint."""
    response = await client.get("/api/firmware/scrapers")
    assert response.status_code == 200
    data = response.json()
    assert "scrapers" in data
    assert "strymon" in data["scrapers"]
    assert "elektron" in data["scrapers"]
    assert "focusrite" in data["scrapers"]
    assert "tascam" in data["scrapers"]
    assert "boss" in data["scrapers"]
    assert "soundforce" in data["scrapers"]
    # VST plugin scrapers
    assert "modartt" in data["scrapers"]
    assert "gforce" in data["scrapers"]
    assert "ikmultimedia" in data["scrapers"]
    assert "moog" in data["scrapers"]
    assert "tal" in data["scrapers"]
    # Additional hardware scrapers
    assert "tcelectronic" in data["scrapers"]
    assert "roland" in data["scrapers"]
    assert "peterson" in data["scrapers"]
    assert "crumar" in data["scrapers"]
    assert "yamaha" in data["scrapers"]
    assert "line6" in data["scrapers"]
    assert "qsc" in data["scrapers"]
    assert "nativeinstruments" in data["scrapers"]
    assert "uaudio" in data["scrapers"]


@pytest.mark.asyncio
async def test_scrape_summary_reports_devices_without_firmware():
    """A device whose firmware fetch yields nothing must be named in the summary.

    Scrapers routinely return success=True with an empty version list, so without
    this the caller cannot tell a clean scrape from one that found nothing.
    """
    from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult
    from src.scrapers.registry import ScraperRegistry
    from src.scrapers import service as scraper_service

    class _StubScraper(BaseScraper):
        manufacturer_name = "Stub Audio"
        manufacturer_slug = "stubaudio"
        manufacturer_website = "https://stub.example.com"

        async def fetch_device_list(self) -> ScraperResult:
            return ScraperResult(
                success=True,
                devices=[
                    ScrapedDevice("Has Firmware", "guitar_pedal", "https://stub.example.com/a"),
                    ScrapedDevice("Empty Success", "guitar_pedal", "https://stub.example.com/b"),
                    ScrapedDevice("Hard Failure", "guitar_pedal", "https://stub.example.com/c"),
                ],
            )

        async def fetch_firmware_versions(self, device_name, firmware_page_url) -> ScraperResult:
            if device_name == "Has Firmware":
                return ScraperResult(success=True, firmware_versions=[ScrapedFirmware("1.0")])
            if device_name == "Empty Success":
                # The silent-failure shape: reports success, returns nothing.
                return ScraperResult(success=True, firmware_versions=[])
            return ScraperResult(success=False, error="page returned no firmware content")

    ScraperRegistry.register(_StubScraper)
    try:
        async with test_session_maker() as db:
            result = await scraper_service.scrape_manufacturer(db, "stubaudio")

        assert result["success"] is True
        # The two causes are reported separately: a product that genuinely has no
        # firmware is not the same as a fetch that broke.
        assert result["devices_without_firmware"] == ["Empty Success"]
        assert result["devices_failed"] == ["Hard Failure"]
    finally:
        ScraperRegistry._scrapers.pop("stubaudio", None)


def _rsc_page(downloads_json: str) -> str:
    """Build a page that mimics Next.js RSC streaming, splitting mid-value.

    The payload is deliberately cut across two pushes so the test fails if the
    parser goes back to scanning the raw document.
    """
    import json as _json

    payload = '{"product":{"downloads":' + downloads_json + '}}'
    half = len(payload) // 2
    parts = [payload[:half], payload[half:]]
    pushes = "".join(
        f'<script>self.__next_f.push([1,{_json.dumps(part)}])</script>' for part in parts
    )
    return f"<html><body>{pushes}</body></html>"


def test_tcelectronic_parses_firmware_from_rsc_payload():
    """Firmware entries with a version are kept; drivers, manuals and notes are not."""
    from src.scrapers.plugins.tcelectronic import TCElectronicScraper

    scraper = TCElectronicScraper()
    downloads = """[
        {"title": "Firmware Release Notes", "downloadType": "Firmware", "version": null,
         "fileUrl": "https://example.invalid/notes"},
        {"title": "Ditto Plus Firmware Mac", "downloadType": "Firmware", "version": "1.0.14",
         "fileUrl": "https://example.invalid/DittoPlus-1.0.14.dmg"},
        {"title": "Quick Start Guide", "downloadType": "Manual", "version": null,
         "fileUrl": "https://example.invalid/qsg.pdf"},
        {"title": "Ditto Plus Firmware PC", "downloadType": "Driver", "version": null,
         "fileUrl": "https://example.invalid/pc"},
        {"title": "Labelled", "downloadType": "Firmware", "version": "Version 1.3.11",
         "fileUrl": "https://example.invalid/x3"}
    ]"""

    parsed = scraper._extract_rsc_downloads(_rsc_page(downloads))
    assert parsed is not None and len(parsed) == 5

    firmware = scraper._firmware_from_downloads(parsed)
    # Release notes have no version, so they drop out; the label is stripped.
    assert [f.version for f in firmware] == ["1.0.14", "1.3.11"]
    assert firmware[0].download_url.endswith("DittoPlus-1.0.14.dmg")


def test_tcelectronic_no_downloads_array_is_a_failure():
    """A page without the payload is a scrape failure, not an absence of firmware."""
    from src.scrapers.plugins.tcelectronic import TCElectronicScraper

    scraper = TCElectronicScraper()
    assert scraper._extract_rsc_downloads("<html><body>Loading</body></html>") is None
    assert scraper._extract_rsc_downloads("") is None


def test_tcelectronic_empty_downloads_is_not_a_failure():
    """A rendered page listing no firmware is a valid, empty result.

    Hall of Fame 2 is the real case: TonePrint app and manuals, no firmware.
    """
    from src.scrapers.plugins.tcelectronic import TCElectronicScraper

    scraper = TCElectronicScraper()
    downloads = """[
        {"title": "TonePrint App", "downloadType": "Software", "version": "4.7.2",
         "fileUrl": "https://example.invalid/toneprint"},
        {"title": "Quick Start Guide", "downloadType": "Manual", "version": null,
         "fileUrl": "https://example.invalid/qsg.pdf"}
    ]"""

    parsed = scraper._extract_rsc_downloads(_rsc_page(downloads))
    assert parsed == parsed and len(parsed) == 2
    # Software and manuals are not firmware, so nothing is reported for the device.
    assert scraper._firmware_from_downloads(parsed) == []


def test_ni_parses_version_from_thread_title():
    """The current version is read out of the update thread's title."""
    from src.scrapers.plugins.native_instruments import NativeInstrumentsScraper

    scraper = NativeInstrumentsScraper()
    cases = [
        ("Official update status - Kontakt (current version: 8.13.0) - Community", "Kontakt", "8.13.0"),
        # Absynth's thread omits the colon; Guitar Rig's slug says 6 but its title says 7.
        ("Official update status - Absynth 6 (current version 6.1) - Community", "Absynth 6", "6.1"),
        ("Official update status - Guitar Rig 7 (current version: 7.0.2) - Community", "Guitar Rig 7", "7.0.2"),
    ]
    for title, product, version in cases:
        match = scraper.TITLE_VERSION.search(title)
        assert match, title
        assert match.group("product").strip() == product
        assert match.group("version").strip() == version


def test_ni_every_product_has_a_version_source():
    """No product may fall through to 'no source configured'."""
    from src.scrapers.plugins.native_instruments import NativeInstrumentsScraper as NI

    names = {name for name, _c, _u in NI.KNOWN_PRODUCTS}
    covered = set(NI.UPDATE_THREADS) | set(NI.SUPERSEDED_VERSIONS) | set(NI.UNVERIFIED_VERSIONS)
    assert names == covered


@pytest.mark.asyncio
async def test_ni_static_versions_are_labelled():
    """Static values carry their provenance so they are not mistaken for a lookup."""
    from src.scrapers.plugins.native_instruments import NativeInstrumentsScraper

    scraper = NativeInstrumentsScraper()

    superseded = await scraper.fetch_firmware_versions("Kontakt 7", "")
    assert superseded.success is True
    assert "Superseded" in superseded.firmware_versions[0].changelog

    unverified = await scraper.fetch_firmware_versions("Raum", "")
    assert unverified.success is True
    assert "Unverified" in unverified.firmware_versions[0].changelog

    unknown = await scraper.fetch_firmware_versions("Nonexistent Plugin", "")
    assert unknown.success is False


def _tal_page() -> str:
    """A TAL product page: shipping version in the download block, dated history."""
    return """
    <html><body>
      <h1>TAL-U-NO-LX</h1>
      <div>Downloads</div>
      <div>v5.1.3</div>
      <div>VST</div>
      <div>Version 5.1.2 / 03.11.2025</div>
      <div>MPE pitch not stay in note release fixed.</div>
      <div>Version 5.1.1 / 17.09.2025</div>
      <div>More MPE options. Framework update.</div>
      <div>Version 4.9.5 / 05.11.2024</div>
      <div>More flexible serial key verification.</div>
    </body></html>
    """


def test_tal_pairs_each_version_with_its_own_date():
    """Each release keeps its own date rather than inheriting a neighbour's.

    The previous parser took the first version and the first date out of the same
    block, so 4.9.5 was recorded with 5.1.2's date of 2025-11-03.
    """
    from src.scrapers.plugins.tal import TALScraper

    parsed = {fw.version: fw for fw in TALScraper()._parse_changelog(_tal_page())}

    assert parsed["4.9.5"].release_date.strftime("%Y-%m-%d") == "2024-11-05"
    assert parsed["5.1.2"].release_date.strftime("%Y-%m-%d") == "2025-11-03"
    assert "serial key" in parsed["4.9.5"].changelog


def test_tal_captures_shipping_version_absent_from_changelog():
    """5.1.3 ships but has no changelog entry, so the download block is the source."""
    from src.scrapers.plugins.tal import TALScraper

    versions = TALScraper()._parse_changelog(_tal_page())

    assert versions[0].version == "5.1.3"
    assert versions[0].release_date is None  # not published, so not invented
    assert len(versions) == 4


def test_tal_download_version_tolerates_spacing():
    """Product pages differ: "v5.1.3" on one, "v 1.9.8" on another."""
    from src.scrapers.plugins.tal import TALScraper

    scraper = TALScraper()
    assert scraper.DOWNLOAD_VERSION.match("v5.1.3").group(1) == "5.1.3"
    assert scraper.DOWNLOAD_VERSION.match("v 1.9.8").group(1) == "1.9.8"


@pytest.mark.asyncio
async def test_tal_merges_known_history_when_page_trims_it():
    """Entries dropped from the page survive via KNOWN_FIRMWARE, without overriding it."""
    from src.scrapers.plugins.tal import TALScraper

    scraper = TALScraper()

    async def _page(*_args, **_kwargs):
        return _tal_page()

    scraper.fetch_page_js = _page
    result = await scraper.fetch_firmware_versions("TAL-U-NO-LX-V2", "https://example.invalid")

    versions = [fw.version for fw in result.firmware_versions]
    assert result.success is True
    # Live parse leads, so the shipping version stays first.
    assert versions[0] == "5.1.3"
    # An old release only present in KNOWN_FIRMWARE is still carried.
    assert "4.5.0" in versions
    # No duplicates from the merge.
    assert len(versions) == len(set(versions))


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


def test_crumar_unverified_version_is_labelled():
    """The D9-X value has no public source and must say so."""
    from src.scrapers.plugins.crumar import CrumarScraper

    entry = CrumarScraper.UNVERIFIED_FIRMWARE["D9-X"][0]
    assert entry[2].startswith("Unverified:")


def test_ikmultimedia_does_not_use_kvr_as_a_source():
    """KVR only exposes reviewer versions now, so it must not be consulted."""
    from src.scrapers.plugins.ikmultimedia import IKMultimediaScraper

    sources = IKMultimediaScraper()._get_sources_for_product("some-slug", "some.bundle")
    assert [s.name for s in sources] == ["MacUpdater"]

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
