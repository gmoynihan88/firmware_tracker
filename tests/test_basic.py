import asyncio
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


def test_notifier_defaults_to_disabled():
    """With no configuration the app still runs; it simply does not deliver.

    _env_file=None keeps this reading the code's defaults rather than whatever the
    developer has in .env -- otherwise a configured machine fails a test that CI,
    which has no .env, passes.
    """
    from src.config import Settings
    from src.notifications.transport import get_notifier

    assert get_notifier(Settings(_env_file=None)).name == "none"


def test_notifier_falls_back_when_misconfigured():
    """A bad transport config disables delivery rather than breaking the tracker."""
    from src.config import Settings
    from src.notifications.transport import get_notifier

    # ntfy selected but no topic to publish to
    assert get_notifier(Settings(_env_file=None, notify_transport="ntfy")).name == "none"
    # a transport that does not exist
    assert get_notifier(
        Settings(_env_file=None, notify_transport="carrier-pigeon")
    ).name == "none"


def test_ntfy_endpoint_and_headers():
    """Title and click-through travel as headers; the body is the message."""
    from src.notifications.transport import NtfyNotifier

    notifier = NtfyNotifier(topic="firmware-tracker-abc", server="https://ntfy.example/")

    assert notifier.endpoint == "https://ntfy.example/firmware-tracker-abc"

    headers = notifier._headers("Pianoteq 9 v9.2.5", "https://example.invalid/dl")
    assert headers["Title"] == "Pianoteq 9 v9.2.5"
    assert headers["Click"] == "https://example.invalid/dl"
    # No URL means no Click header at all, rather than an empty one.
    assert "Click" not in notifier._headers("No link", None)


def test_ntfy_title_survives_non_latin1_characters():
    """Headers are latin-1; product names are not always.

    A raw encode would raise inside send() and lose the delivery.
    """
    from src.notifications.transport import NtfyNotifier

    headers = NtfyNotifier(topic="t")._headers("TAL-U-NO-LX — 5.1.3", None)
    assert headers["Title"].encode("latin-1")


@pytest.mark.asyncio
async def test_ntfy_send_failure_is_swallowed():
    """A transport failure must not propagate; the Notification row is what matters."""
    from src.notifications.transport import NtfyNotifier

    # Port 1 is not listenable, so the POST fails at connect.
    notifier = NtfyNotifier(topic="t", server="http://127.0.0.1:1", timeout=1)
    assert await notifier.send("Title", "Message") is False


@pytest.mark.asyncio
async def test_null_notifier_reports_not_delivered():
    from src.notifications.transport import NullNotifier

    assert await NullNotifier().send("Title", "Message") is False


def test_is_behind_compares_numerically_not_as_strings():
    """String inequality would flag a device running ahead of the published version.

    That happens in practice: a hotfix that never reached the vendor's list. It also
    gets 9.2.10 vs 9.2.9 wrong, which string ordering reverses.
    """
    from src.notifications.reconcile import is_behind

    assert is_behind("2.0.5", "2.0.6") is True
    assert is_behind("9.2.4", "9.2.5") is True
    assert is_behind("9.2.9", "9.2.10") is True   # string compare would say False
    assert is_behind("2.0.6", "2.0.6") is False
    assert is_behind("1.7.1", "1.7.0") is False   # installed is ahead
    # Nothing to compare against.
    assert is_behind("", "1.0.0") is False
    assert is_behind("1.0.0", "") is False


@pytest.mark.asyncio
async def test_reconcile_notifies_a_device_left_behind():
    """The case scraping misses: latest was already known when the install was recorded."""
    from src.devices.schemas import (
        DeviceModelCreate, FirmwareVersionCreate, ManufacturerCreate, MyDeviceCreate,
    )
    from src.devices import service as ds
    from src.devices.models import DeviceCategory
    from src.notifications.reconcile import reconcile_notifications

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(db, ManufacturerCreate(name="Stub", slug="stub"))
        model = await ds.create_device_model(db, DeviceModelCreate(
            manufacturer_id=mfr.id, name="Stub Synth", category=DeviceCategory.SYNTHESIZER,
        ))
        await ds.create_firmware_version(db, FirmwareVersionCreate(
            device_model_id=model.id, version="2.0.6", is_latest=True,
        ))
        # Installed version recorded after the latest was already in the database.
        await ds.create_my_device(db, MyDeviceCreate(
            device_model_id=model.id, current_firmware_version="2.0.5", notify_on_update=True,
        ))

        first = await reconcile_notifications(db)
        assert first["notifications_created"] == 1

        # Idempotent: running again must not notify a second time.
        second = await reconcile_notifications(db)
        assert second["notifications_created"] == 0


@pytest.mark.asyncio
async def test_reconcile_skips_devices_with_no_installed_version():
    """Without an installed version a device is unrecorded, not behind."""
    from src.devices.schemas import (
        DeviceModelCreate, FirmwareVersionCreate, ManufacturerCreate, MyDeviceCreate,
    )
    from src.devices import service as ds
    from src.devices.models import DeviceCategory
    from src.notifications.reconcile import reconcile_notifications

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(db, ManufacturerCreate(name="Stub2", slug="stub2"))
        model = await ds.create_device_model(db, DeviceModelCreate(
            manufacturer_id=mfr.id, name="Stub Pedal", category=DeviceCategory.GUITAR_PEDAL,
        ))
        await ds.create_firmware_version(db, FirmwareVersionCreate(
            device_model_id=model.id, version="1.5.0", is_latest=True,
        ))
        await ds.create_my_device(db, MyDeviceCreate(
            device_model_id=model.id, notify_on_update=True,
        ))

        result = await reconcile_notifications(db)

        assert result["notifications_created"] == 0
        assert result["devices_without_installed_version"] == 1


@pytest.mark.asyncio
async def test_reconcile_respects_notify_opt_out(client):
    """A device with notify_on_update off is never notified."""
    from src.devices.schemas import (
        DeviceModelCreate, FirmwareVersionCreate, ManufacturerCreate, MyDeviceCreate,
    )
    from src.devices import service as ds
    from src.devices.models import DeviceCategory
    from src.notifications.reconcile import reconcile_notifications

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(db, ManufacturerCreate(name="Stub3", slug="stub3"))
        model = await ds.create_device_model(db, DeviceModelCreate(
            manufacturer_id=mfr.id, name="Quiet Box", category=DeviceCategory.OTHER,
        ))
        await ds.create_firmware_version(db, FirmwareVersionCreate(
            device_model_id=model.id, version="3.0.0", is_latest=True,
        ))
        await ds.create_my_device(db, MyDeviceCreate(
            device_model_id=model.id, current_firmware_version="1.0.0", notify_on_update=False,
        ))

        assert (await reconcile_notifications(db))["notifications_created"] == 0

    # And the endpoint is reachable.
    response = await client.post("/api/firmware/reconcile-notifications")
    assert response.status_code == 200
    assert "notifications_created" in response.json()


def _focusrite_category_page() -> str:
    """A category listing: product links one level below, plus links that are not products."""
    return """
    <html><body>
      <nav><a href="/focusrite">Focusrite</a></nav>
      <a href="/focusrite/scarlett-4th-gen">Scarlett 4th Gen</a>
      <a href="/focusrite/scarlett-4th-gen/scarlett-2i2-4th-gen">Scarlett 2i2 4th Gen</a>
      <a href="/focusrite/scarlett-4th-gen/scarlett-solo-4th-gen">Scarlett Solo 4th Gen</a>
      <a href="/focusrite/scarlett-4th-gen/scarlett-2i2-4th-gen/extra">Too deep</a>
      <a href="/other/thing">Unrelated</a>
    </body></html>
    """


def test_focusrite_normalises_names_to_match_existing_rows():
    """The site's spelling differs from the database's; unnormalised it duplicates rows.

    Focusrite writes "Clarett⁺" with a superscript plus (U+207A) and is inconsistent
    about capitalising "gen".
    """
    from src.scrapers.plugins.focusrite import FocusriteScraper

    scraper = FocusriteScraper()

    assert scraper._normalise_name("Clarett⁺ 2Pre") == "Clarett+ 2Pre"
    assert scraper._normalise_name("Scarlett 18i20 3rd gen") == "Scarlett 18i20 3rd Gen"
    assert scraper._normalise_name("Scarlett 8i6 3rd gen") == "Scarlett 8i6 3rd Gen"
    # Already correct names are left alone.
    assert scraper._normalise_name("Scarlett 2i2 4th Gen") == "Scarlett 2i2 4th Gen"
    assert scraper._normalise_name("Vocaster One") == "Vocaster One"


def test_focusrite_detects_a_404_page():
    """Focusrite serves its 404 with full site chrome, so length alone is not enough."""
    from src.scrapers.plugins.focusrite import FocusriteScraper

    scraper = FocusriteScraper()
    filler = "Site navigation and footer boilerplate. " * 80  # comfortably over the floor

    not_found = f"<html><body><h1>Page not found</h1><p>The requested page could not be found.</p>{filler}</body></html>"
    assert scraper._page_rendered(not_found) is False

    assert scraper._page_rendered(f"<html><body>{filler}</body></html>") is True
    assert scraper._page_rendered("<html><body>Loading</body></html>") is False
    assert scraper._page_rendered(None) is False


@pytest.mark.asyncio
async def test_focusrite_discovers_products_from_a_category_listing():
    """Only links exactly one level below the category are products."""
    from src.scrapers.plugins.focusrite import FocusriteScraper

    scraper = FocusriteScraper()

    async def _page(*_args, **_kwargs):
        # Pad so _page_rendered accepts it.
        return _focusrite_category_page() + "<p>" + ("padding text. " * 200) + "</p>"

    scraper.fetch_page_js = _page
    devices = await scraper._products_in_category("scarlett-4th-gen")

    names = sorted(d.name for d in devices)
    assert names == ["Scarlett 2i2 4th Gen", "Scarlett Solo 4th Gen"]
    assert devices[0].firmware_page_url.startswith("https://downloads.focusrite.com/focusrite/")


@pytest.mark.asyncio
async def test_focusrite_reports_no_firmware_without_fetching():
    """Focusrite publishes no per-device version, so this is an empty success.

    It must not fetch: 28 pointless page loads previously consumed ~95s of the 120s
    per-manufacturer budget and timed out the last devices.
    """
    from src.scrapers.plugins.focusrite import FocusriteScraper

    scraper = FocusriteScraper()

    async def _explode(*_args, **_kwargs):
        raise AssertionError("fetch_firmware_versions must not fetch the product page")

    scraper.fetch_page_js = _explode
    result = await scraper.fetch_firmware_versions("Scarlett 2i2 4th Gen", "https://example.invalid")

    assert result.success is True
    assert result.firmware_versions == []

def test_scrape_budget_scales_with_device_count():
    """A fixed budget measures nothing; a 40-device scraper needs more than a 3-device one.

    At the old fixed 120s, Boss (16 devices at ~7s each) sat at 93% of budget while
    Native Instruments (40 devices) used 13%.
    """
    from src.scrapers.service import scrape_budget_for

    assert scrape_budget_for(3) < scrape_budget_for(16) < scrape_budget_for(40)
    # Comfortably above the observed worst case of ~7s per device.
    assert scrape_budget_for(16) >= 16 * 10
    # Degenerate counts do not produce a negative budget.
    assert scrape_budget_for(0) > 0
    assert scrape_budget_for(-5) > 0


@pytest.mark.asyncio
async def test_scrape_reports_partial_results_when_budget_runs_out(monkeypatch):
    """Running out of budget must return what was done, not discard the whole run.

    The old outer wait_for cancelled the scrape and replaced the summary with a bare
    failure, even though each device's data had already been committed -- so the
    database was right while the report claimed total failure.
    """
    from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult
    from src.scrapers.registry import ScraperRegistry
    from src.scrapers import service as scraper_service

    class _SlowScraper(BaseScraper):
        manufacturer_name = "Slow Audio"
        manufacturer_slug = "slowaudio"
        manufacturer_website = "https://slow.example.com"

        async def fetch_device_list(self) -> ScraperResult:
            return ScraperResult(
                success=True,
                devices=[
                    ScrapedDevice(f"Slow {i}", "guitar_pedal", f"https://slow.example.com/{i}")
                    for i in range(5)
                ],
            )

        async def fetch_firmware_versions(self, device_name, firmware_page_url) -> ScraperResult:
            await asyncio.sleep(0.05)
            return ScraperResult(success=True, firmware_versions=[ScrapedFirmware("1.0")])

    # A budget that expires after roughly the first couple of devices.
    monkeypatch.setattr(scraper_service, "scrape_budget_for", lambda n: 0.06)

    ScraperRegistry.register(_SlowScraper)
    try:
        async with test_session_maker() as db:
            result = await scraper_service.scrape_manufacturer(db, "slowaudio")

        # The run reports success with partial results rather than failing outright.
        assert result["success"] is True
        assert result["devices_not_checked"], "expected some devices to be skipped"
        # And it did not silently skip everything.
        checked = 5 - len(result["devices_not_checked"])
        assert checked >= 1
    finally:
        ScraperRegistry._scrapers.pop("slowaudio", None)


def _line6_firmware_page() -> str:
    """The firmware listing: sidebar holds version, date and compatible products.

    The description deliberately quotes a version in prose, which is how the real
    page reads and what a free-text scan would wrongly pick up as a release.
    """
    return """
    <html><body>
      <div class="release-details">
        <div class="sidebar">
          <b>Version 3.80.0</b><br><b>Released 11/19/24</b><br><br>
          Works with:<br><b>Helix</b><br><b>HX Stomp</b>
        </div>
        <div class="description">Adds new cabs. 3.50 renamed the Mono subcategory.</div>
      </div>
      <div class="release-details">
        <div class="sidebar">
          <b>Version 3.15.0</b><br><b>Released 2/8/22</b><br><br>
          Works with:<br><b>Helix</b>
        </div>
        <div class="description">Earlier release.</div>
      </div>
      <div class="release-details">
        <div class="sidebar">
          <b>Version 2.06.0</b><br><b>Released 7/16/24</b><br><br>
          Works with:<br><b>Relay G10TII Transmitter</b>
        </div>
        <div class="description">Wireless transmitter update.</div>
      </div>
    </body></html>
    """


def test_line6_parses_products_from_the_sidebar_only():
    """One release can apply to several products, and descriptions quote versions.

    Scanning the description text would invent a 3.50 release that this page never
    lists as its own entry.
    """
    from src.scrapers.plugins.line6 import Line6Scraper

    catalogue = Line6Scraper()._parse_catalogue(_line6_firmware_page())

    # Note the ordering: "HX Stomp" sorts before "Helix", uppercase X preceding
    # lowercase e.
    assert sorted(catalogue) == ["HX Stomp", "Helix", "Relay G10TII Transmitter"]
    # Helix appears in two entries; HX Stomp only shares the first.
    assert [fw.version for fw in catalogue["Helix"]] == ["3.80.0", "3.15.0"]
    assert [fw.version for fw in catalogue["HX Stomp"]] == ["3.80.0"]
    assert catalogue["Helix"][0].release_date.strftime("%Y-%m-%d") == "2024-11-19"


def test_line6_orders_releases_newest_first_numerically():
    """3.15.0 must not sort above 3.80.0, as string ordering would have it."""
    from src.scrapers.plugins.line6 import Line6Scraper

    catalogue = Line6Scraper()._parse_catalogue(_line6_firmware_page())
    assert catalogue["Helix"][0].version == "3.80.0"


@pytest.mark.asyncio
async def test_line6_fetches_the_listing_once_for_every_device():
    """One page carries all products; fetching it per device wastes the budget."""
    from src.scrapers.plugins.line6 import Line6Scraper

    scraper = Line6Scraper()
    calls = []

    async def _page(*_args, **_kwargs):
        calls.append(1)
        return _line6_firmware_page()

    scraper.fetch_page_js = _page

    for name in ("Helix", "HX Stomp", "Relay G10II"):
        result = await scraper.fetch_firmware_versions(name, scraper.FIRMWARE_URL)
        assert result.success is True, name

    assert len(calls) == 1, f"expected one fetch, made {len(calls)}"


@pytest.mark.asyncio
async def test_line6_maps_device_names_to_their_release_names():
    """The G10II ships firmware as the G10TII transmitter, under a different name."""
    from src.scrapers.plugins.line6 import Line6Scraper

    scraper = Line6Scraper()

    async def _page(*_args, **_kwargs):
        return _line6_firmware_page()

    scraper.fetch_page_js = _page

    mapped = await scraper.fetch_firmware_versions("Relay G10II", scraper.FIRMWARE_URL)
    assert mapped.success is True
    assert mapped.firmware_versions[0].version == "2.06.0"

    # A product genuinely absent from the listing is a failure, not an empty success.
    missing = await scraper.fetch_firmware_versions("Nonexistent Pedal", scraper.FIRMWARE_URL)
    assert missing.success is False


@pytest.mark.asyncio
async def test_scrape_notifications_follow_the_same_rule_as_reconciliation():
    """Both notification paths must agree on what "behind" means.

    The scrape-time path used a plain !=, which notified devices whose installed
    version is unknown (None equals nothing) and devices running a build newer than
    the vendor publishes. Reconciliation skipped both. A Relay G10II with no recorded
    version was told about firmware 2.06.0 on that basis.
    """
    from src.devices.schemas import (
        DeviceModelCreate, FirmwareVersionCreate, ManufacturerCreate, MyDeviceCreate,
    )
    from src.devices import service as ds
    from src.devices.models import DeviceCategory
    from src.scrapers.service import create_update_notifications

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(db, ManufacturerCreate(name="NotifyCo", slug="notifyco"))

        async def _model(name):
            model = await ds.create_device_model(db, DeviceModelCreate(
                manufacturer_id=mfr.id, name=name, category=DeviceCategory.OTHER,
            ))
            await ds.create_firmware_version(db, FirmwareVersionCreate(
                device_model_id=model.id, version="2.0.6", is_latest=True,
            ))
            return model

        unknown = await _model("Unknown Install")
        ahead = await _model("Running Ahead")
        behind = await _model("Genuinely Behind")

        # No installed version recorded at all.
        await ds.create_my_device(db, MyDeviceCreate(
            device_model_id=unknown.id, notify_on_update=True,
        ))
        # Installed build is newer than what the vendor lists.
        await ds.create_my_device(db, MyDeviceCreate(
            device_model_id=ahead.id, current_firmware_version="2.0.7", notify_on_update=True,
        ))
        await ds.create_my_device(db, MyDeviceCreate(
            device_model_id=behind.id, current_firmware_version="2.0.5", notify_on_update=True,
        ))

        assert await create_update_notifications(db, unknown.id, "2.0.6") == 0
        assert await create_update_notifications(db, ahead.id, "2.0.6") == 0
        assert await create_update_notifications(db, behind.id, "2.0.6") == 1


@pytest.mark.asyncio
async def test_dashboard_separates_unknown_firmware_from_updates(client):
    """A device with no recorded installed version is unknown, not behind.

    The dashboard previously fell through to "Update Available" whenever a latest
    version existed, which is a guess: 10 of 11 unrecorded devices were shown as
    needing an update.
    """
    from src.devices.schemas import (
        DeviceModelCreate, FirmwareVersionCreate, ManufacturerCreate, MyDeviceCreate,
    )
    from src.devices import service as ds
    from src.devices.models import DeviceCategory

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(db, ManufacturerCreate(name="DashCo", slug="dashco"))

        async def _tracked(name, installed):
            model = await ds.create_device_model(db, DeviceModelCreate(
                manufacturer_id=mfr.id, name=name, category=DeviceCategory.OTHER,
            ))
            await ds.create_firmware_version(db, FirmwareVersionCreate(
                device_model_id=model.id, version="2.0.6", is_latest=True,
            ))
            await ds.create_my_device(db, MyDeviceCreate(
                device_model_id=model.id, current_firmware_version=installed,
                notify_on_update=True,
            ))

        await _tracked("No Version Recorded", None)
        await _tracked("Behind", "2.0.5")
        await _tracked("Up To Date", "2.0.6")

    response = await client.get("/")
    assert response.status_code == 200
    html = response.text

    assert html.count('data-status="unknown"') == 1
    assert html.count('data-status="update"') == 1
    assert html.count('data-status="current"') == 1
    # And the filter offers the new state.
    assert "Firmware Unknown" in html


@pytest.mark.asyncio
async def test_dashboard_does_not_flag_a_device_running_ahead(client):
    """Installed newer than published is current, not an update.

    The old check used !=, so a hotfix that never reached the vendor's list read as
    an update being available.
    """
    from src.devices.schemas import (
        DeviceModelCreate, FirmwareVersionCreate, ManufacturerCreate, MyDeviceCreate,
    )
    from src.devices import service as ds
    from src.devices.models import DeviceCategory

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(db, ManufacturerCreate(name="AheadCo", slug="aheadco"))
        model = await ds.create_device_model(db, DeviceModelCreate(
            manufacturer_id=mfr.id, name="Ahead Synth", category=DeviceCategory.SYNTHESIZER,
        ))
        await ds.create_firmware_version(db, FirmwareVersionCreate(
            device_model_id=model.id, version="1.7.0", is_latest=True,
        ))
        await ds.create_my_device(db, MyDeviceCreate(
            device_model_id=model.id, current_firmware_version="1.7.1", notify_on_update=True,
        ))

    html = (await client.get("/")).text
    assert html.count('data-status="current"') == 1
    assert 'data-status="update"' not in html


def _gforce_releases_page() -> str:
    """The Updates And Releases page: one div.update-release-item per release."""
    return """
    <html><body>
      <div class="update-release-item">
        <span>06/30/2026</span>
        <div class="text-content">
          <a>Oberheim OB-E&#174;</a>
          <div class="description">
            <h3><strong>v2.5.1</strong></h3>
            <ul><li>Fixed voice allocation.</li></ul>
            <a class="product-link" href="/product/ob-e/">View Oberheim OB-E&#174;</a>
          </div>
        </div>
      </div>
      <div class="update-release-item">
        <span>04/03/2023</span>
        <div class="text-content">
          <a>Oberheim OB-E&#174;</a>
          <div class="description">
            <h3><strong>v2.0</strong></h3>
            <ul><li>Earlier release.</li></ul>
            <a class="product-link" href="/product/ob-e/">View Oberheim OB-E&#174;</a>
          </div>
        </div>
      </div>
      <div class="update-release-item">
        <span>02/11/2026</span>
        <div class="text-content">
          <a>VSM IV</a>
          <div class="description">
            <h3><strong>v1.1</strong></h3>
            <ul><li>Fixed stereo sample playback.</li></ul>
            <a class="product-link" href="/product/vsm-iv/">View VSM IV</a>
          </div>
        </div>
      </div>
    </body></html>
    """


def test_gforce_strips_trademark_symbols_from_product_names():
    """GForce writes "Oberheim OB-E®"; the database row is "Oberheim OB-E".

    Without normalising, a scrape creates a second row and orphans the first.
    """
    from src.scrapers.plugins.gforce import GForceScraper

    releases = GForceScraper()._parse_releases(_gforce_releases_page())

    assert "Oberheim OB-E" in releases
    assert not any("®" in name for name in releases)


def test_gforce_orders_releases_and_keeps_dates():
    from src.scrapers.plugins.gforce import GForceScraper

    releases = GForceScraper()._parse_releases(_gforce_releases_page())

    obe = releases["Oberheim OB-E"]
    assert [fw.version for fw in obe] == ["2.5.1", "2.0"]
    assert obe[0].release_date.strftime("%Y-%m-%d") == "2026-06-30"
    assert "voice allocation" in obe[0].changelog
    assert obe[0].download_url.endswith("/product/ob-e/")


@pytest.mark.asyncio
async def test_gforce_resolves_a_renamed_product():
    """Virtual String Machine is now listed as VSM IV."""
    from src.scrapers.plugins.gforce import GForceScraper

    scraper = GForceScraper()

    async def _page(*_args, **_kwargs):
        return _gforce_releases_page()

    scraper.fetch_page_js = _page

    renamed = await scraper.fetch_firmware_versions("Virtual String Machine", scraper.RELEASES_URL)
    assert renamed.success is True
    assert renamed.firmware_versions[0].version == "1.1"


@pytest.mark.asyncio
async def test_gforce_superseded_product_is_not_a_failure():
    """M-Tron Pro is superseded and has no releases of its own.

    Reporting it as failed would be wrong; the absence is a fact about the product.
    """
    from src.scrapers.plugins.gforce import GForceScraper

    scraper = GForceScraper()

    async def _page(*_args, **_kwargs):
        return _gforce_releases_page()

    scraper.fetch_page_js = _page

    superseded = await scraper.fetch_firmware_versions("M-Tron Pro", scraper.RELEASES_URL)
    assert superseded.success is True
    assert superseded.firmware_versions == []

    # Something genuinely unlisted still fails.
    unknown = await scraper.fetch_firmware_versions("Not A Product", scraper.RELEASES_URL)
    assert unknown.success is False


def _moog_update_page() -> str:
    """A Moog software update page: download blurb plus a Change Log."""
    return """
    <html><body>
      <div>
        <span>macOS All Formats v1.2.0</span>
        <span>Windows All Formats v1.2.0</span>
      </div>
      <div>
        <h2>Change Log</h2>
        <p class="sub-header">1.2.0</p>
        <p>Added Apple Pencil support on iOS.</p>
        <p>Performance improvements to internal DSP.</p>
        <p class="sub-header">1.1.0</p>
        <p>Fix for envelope CV not working correctly anymore in v1.1.0.</p>
        <p class="sub-header">1.0.0</p>
        <p>Initial release.</p>
      </div>
    </body></html>
    """


def test_moog_reads_the_whole_changelog_not_just_the_download():
    """The old parser took only the download blurb, losing the history and its notes."""
    from src.scrapers.plugins.moog import MoogScraper

    versions = MoogScraper()._parse_software_update_page(_moog_update_page())

    assert [fw.version for fw in versions] == ["1.2.0", "1.1.0", "1.0.0"]
    assert "Apple Pencil" in versions[0].changelog
    # Notes stop at the next version rather than swallowing the rest of the log.
    assert "envelope CV" not in versions[0].changelog


def test_moog_keeps_a_shipping_build_absent_from_the_changelog():
    """The download blurb can name a build the Change Log does not list."""
    from src.scrapers.plugins.moog import MoogScraper

    html = _moog_update_page().replace("All Formats v1.2.0", "All Formats v1.3.0")
    versions = MoogScraper()._parse_software_update_page(html)

    assert versions[0].version == "1.3.0"
    assert "1.2.0" in [fw.version for fw in versions]


@pytest.mark.asyncio
async def test_moog_products_without_a_published_version():
    """Three products are App Store apps whose Moog pages 404.

    Every software-update slug except mariana returns the same generic shell -- even
    invented ones -- so there is nothing to read rather than something broken.
    """
    from src.scrapers.plugins.moog import MoogScraper

    scraper = MoogScraper()

    async def _explode(*_args, **_kwargs):
        raise AssertionError("must not fetch for a product with no published version")

    scraper.fetch_page = _explode

    for name in ("Animoog Z", "Moog Model 15", "Minimoog Model D App"):
        result = await scraper.fetch_firmware_versions(name, "https://example.invalid")
        assert result.success is True, name
        assert result.firmware_versions == []


@pytest.mark.asyncio
async def test_moog_reports_the_generic_shell_as_a_failure():
    """A page with no version at all is a failure, not an empty success."""
    from src.scrapers.plugins.moog import MoogScraper

    scraper = MoogScraper()

    async def _shell(*_args, **_kwargs):
        return "<html><body><p>Moog Music</p><p>Download</p></body></html>"

    scraper.fetch_page = _shell
    result = await scraper.fetch_firmware_versions("Mariana", "https://example.invalid")

    assert result.success is False
    assert "shell" in result.error
