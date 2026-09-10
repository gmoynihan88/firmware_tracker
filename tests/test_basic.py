import asyncio
import json
import logging
import os
import sqlite3
import time
from pathlib import Path

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
    assert "izotope" in data["scrapers"]
    assert "uaudio" in data["scrapers"]
    assert "steinberg" in data["scrapers"]
    assert "eventide" in data["scrapers"]


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

def test_soundforce_parses_both_page_formats():
    """WordPress pages write "V1.11:"; the Notion pages prefix a date."""
    from src.scrapers.plugins.soundforce import SoundForceScraper

    html = """
    <html><body>
      <p>V1.11:</p><p>MacOS updater app download</p>
      <p>V1.11:</p><p>Windows updater</p>
      <p>V1.10:</p><p>MacOS updater app download</p>
      <p>25/11/2025: V1.9:</p><p>Notion-style entry with a date</p>
    </body></html>
    """
    versions = SoundForceScraper()._parse_updates(html)

    # Each version is listed twice, once per platform; they must not double up.
    assert [fw.version for fw in versions] == ["1.11", "1.10", "1.9"]
    assert versions[0].release_date is None          # WordPress entries carry no date
    assert versions[2].release_date.strftime("%Y-%m-%d") == "2025-11-25"


def test_soundforce_orders_versions_numerically():
    """1.11 must outrank 1.9, which string ordering reverses."""
    from src.scrapers.plugins.soundforce import SoundForceScraper

    html = "<html><body><p>V1.9:</p><p>V1.11:</p><p>V1.10:</p></body></html>"
    versions = SoundForceScraper()._parse_updates(html)

    assert [fw.version for fw in versions] == ["1.11", "1.10", "1.9"]


@pytest.mark.asyncio
async def test_soundforce_resolves_update_pages_from_the_support_page():
    """URLs come from the Support page, not from hardcoded WordPress page ids.

    Two of the old ?page_id= values had changed and returned an identical
    1037-character "Page Not Found".
    """
    from src.scrapers.plugins.soundforce import SoundForceScraper

    scraper = SoundForceScraper()
    support = """
    <html><body>
      <a href="https://sound-force.nl/?page_id=5155">SFC-60 V3 updates</a>
      <a href="https://sound-force.nl/?page_id=5145">SFC-5 V2 updates</a>
      <a href="https://sound-force.nl/shop">Webshop</a>
    </body></html>
    """
    fetched = []

    async def _page(url, *_args, **_kwargs):
        fetched.append(url)
        if url == scraper.SUPPORT_URL:
            return support
        return "<html><body><p>V2.7:</p></body></html>"

    scraper.fetch_page_js = _page

    result = await scraper.fetch_firmware_versions("SFC-5", scraper.SUPPORT_URL)
    assert result.success is True
    assert result.firmware_versions[0].version == "2.7"
    # It followed the link the support page gave, not a hardcoded id.
    assert "page_id=5145" in fetched[-1]

    # A product the support page does not link is a failure, not an empty success.
    missing = await scraper.fetch_firmware_versions("SFC-8", scraper.SUPPORT_URL)
    assert missing.success is False


@pytest.mark.asyncio
async def test_soundforce_fetches_the_support_page_once():
    """The index is shared by every device."""
    from src.scrapers.plugins.soundforce import SoundForceScraper

    scraper = SoundForceScraper()
    support_fetches = []

    async def _page(url, *_args, **_kwargs):
        if url == scraper.SUPPORT_URL:
            support_fetches.append(url)
            return '<html><body><a href="/u">SFC-60 V3 updates</a><a href="/u">SFC-5 V2 updates</a></body></html>'
        return "<html><body><p>V1.11:</p></body></html>"

    scraper.fetch_page_js = _page

    for name in ("SFC-60", "SFC-5"):
        assert (await scraper.fetch_firmware_versions(name, scraper.SUPPORT_URL)).success

    assert len(support_fetches) == 1


@pytest.mark.asyncio
async def test_health_is_liveness_and_touches_nothing(client):
    """Liveness must not depend on the database.

    If it did, a slow disk would have the orchestrator kill and replace tasks, which
    does not fix a slow disk.
    """
    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["uptime_seconds"] >= 0


@pytest.mark.asyncio
async def test_readiness_reports_the_database(client):
    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


@pytest.mark.asyncio
async def test_readiness_returns_503_when_the_database_is_unreachable(client):
    """A failing probe answers 503 with a reason, rather than raising.

    A health check that returns an empty error is one you end up debugging by hand.
    """
    from src.database import get_db
    from src.main import app

    async def _broken_db():
        class _Failing:
            async def execute(self, *_args, **_kwargs):
                raise RuntimeError("unable to open database file")

            async def close(self):
                return None

        yield _Failing()

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _broken_db
    try:
        response = await client.get("/health/ready")
    finally:
        if previous is not None:
            app.dependency_overrides[get_db] = previous
        else:
            app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["database"] == "unreachable"
    assert "unable to open database file" in body["detail"]


@pytest.mark.asyncio
async def test_health_endpoints_are_not_under_the_api_prefix(client):
    """A load balancer does not know about /api and cannot present credentials."""
    from src.main import app

    paths = set(app.openapi()["paths"])
    assert "/health" in paths and "/health/ready" in paths
    assert not any(p.startswith("/api") and "health" in p for p in paths)


# --- authentication -------------------------------------------------------

@pytest.fixture
def auth_enabled():
    """Turn authentication on for one test, then put it back.

    The middleware holds the same Settings instance the app was built with, and
    get_settings() is cached, so mutating that object switches auth on without
    rebuilding the app.
    """
    from src.auth.security import generate_secret_key, hash_password
    from src.config import get_settings

    settings = get_settings()
    before = (settings.auth_password_hash, settings.secret_key, settings.api_key)

    settings.auth_password_hash = hash_password("correct horse")
    settings.secret_key = generate_secret_key()
    settings.api_key = "test-api-key"
    try:
        yield settings
    finally:
        settings.auth_password_hash, settings.secret_key, settings.api_key = before


def test_password_hashing_round_trip():
    """scrypt hashes verify, and a malformed stored value denies rather than raises."""
    from src.auth.security import hash_password, verify_password

    stored = hash_password("correct horse")
    assert stored.startswith("scrypt$")
    assert verify_password("correct horse", stored) is True
    assert verify_password("Correct Horse", stored) is False
    # A broken value in .env must deny access, not crash every request.
    assert verify_password("anything", "not-a-hash") is False
    assert verify_password("anything", "") is False


def test_session_tokens_reject_tampering_and_expiry():
    from src.auth.security import generate_secret_key, issue_token, read_token

    secret = generate_secret_key()
    token = issue_token(secret, 3600)

    assert read_token(token, secret)["sub"] == "owner"
    assert read_token(token, generate_secret_key()) is None      # signed with another key
    assert read_token(token[:-2] + "xy", secret) is None          # signature altered
    assert read_token(issue_token(secret, -1), secret) is None    # already expired
    assert read_token("", secret) is None
    assert read_token("no-dot", secret) is None


@pytest.mark.asyncio
async def test_auth_disabled_leaves_everything_open(client):
    """Default install keeps working with no configuration."""
    assert (await client.get("/")).status_code == 200
    assert (await client.get("/api/manufacturers")).status_code == 200


@pytest.mark.asyncio
async def test_api_requires_authentication_when_enabled(auth_enabled, client):
    response = await client.get("/api/manufacturers")

    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


@pytest.mark.asyncio
async def test_browser_is_redirected_to_the_login_page(auth_enabled, client):
    """A browser should land on the form; curl should get a status code."""
    response = await client.get("/", headers={"accept": "text/html"})

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


@pytest.mark.asyncio
async def test_health_endpoints_stay_reachable_when_auth_is_on(auth_enabled, client):
    """A load balancer cannot present credentials."""
    assert (await client.get("/health")).status_code == 200
    assert (await client.get("/health/ready")).status_code == 200


@pytest.mark.asyncio
async def test_login_sets_a_session_that_grants_access(auth_enabled, client):
    bad = await client.post("/login", data={"password": "wrong"})
    assert bad.status_code == 401
    assert "Incorrect password" in bad.text

    good = await client.post("/login", data={"password": "correct horse"})
    assert good.status_code == 303
    assert good.headers["location"] == "/"

    from src.auth.middleware import SESSION_COOKIE
    assert SESSION_COOKIE in good.cookies

    # The client keeps the cookie, so the API is now reachable.
    assert (await client.get("/api/manufacturers")).status_code == 200

    await client.get("/logout")
    assert (await client.get("/api/manufacturers")).status_code == 401


@pytest.mark.asyncio
async def test_api_key_works_for_programmatic_callers(auth_enabled, client):
    assert (await client.get("/api/manufacturers", headers={"x-api-key": "test-api-key"})).status_code == 200
    assert (await client.get("/api/manufacturers", headers={"x-api-key": "wrong"})).status_code == 401


@pytest.mark.asyncio
async def test_api_key_is_ignored_when_none_is_configured(auth_enabled, client):
    """An unset API key must not mean "any key works", or "no key works either"."""
    auth_enabled.api_key = ""
    assert (await client.get("/api/manufacturers", headers={"x-api-key": ""})).status_code == 401
    assert (await client.get("/api/manufacturers", headers={"x-api-key": "anything"})).status_code == 401


def test_auth_stays_off_if_only_half_configured():
    """A password with no secret key cannot sign sessions, so it must not half-enable."""
    from src.auth.middleware import auth_is_enabled
    from src.config import Settings

    assert auth_is_enabled(Settings(_env_file=None, auth_password_hash="scrypt$a$b", secret_key="")) is False
    assert auth_is_enabled(Settings(_env_file=None, auth_password_hash="", secret_key="k")) is False
    assert auth_is_enabled(Settings(_env_file=None, auth_password_hash="scrypt$a$b", secret_key="k")) is True


@pytest.mark.asyncio
async def test_dashboard_renders_a_table_with_the_expected_columns(client):
    """One row per device, dense enough to scan 71 of them."""
    from src.devices.schemas import (
        DeviceModelCreate, FirmwareVersionCreate, ManufacturerCreate, MyDeviceCreate,
    )
    from src.devices import service as ds
    from src.devices.models import DeviceCategory

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(db, ManufacturerCreate(name="TableCo", slug="tableco"))
        model = await ds.create_device_model(db, DeviceModelCreate(
            manufacturer_id=mfr.id, name="Table Synth", category=DeviceCategory.SYNTHESIZER,
        ))
        await ds.create_firmware_version(db, FirmwareVersionCreate(
            device_model_id=model.id, version="2.0.6", is_latest=True,
        ))
        await ds.create_my_device(db, MyDeviceCreate(
            device_model_id=model.id, current_firmware_version="2.0.5", notify_on_update=True,
        ))

    html = (await client.get("/")).text

    for column in ("Vendor", "Product", "Category", "Installed", "Latest", "Status"):
        assert f">{column}<" in html, column

    assert html.count('class="device-row') == 1
    assert "TableCo" in html
    assert "2.0.5" in html and "2.0.6" in html
    # The row still carries the filter attributes.
    assert 'data-status="update"' in html
    assert 'data-brand="tableco"' in html


@pytest.mark.asyncio
async def test_dashboard_row_links_to_the_device_detail_page(client):
    from src.devices.schemas import (
        DeviceModelCreate, ManufacturerCreate, MyDeviceCreate,
    )
    from src.devices import service as ds
    from src.devices.models import DeviceCategory

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(db, ManufacturerCreate(name="LinkCo", slug="linkco"))
        model = await ds.create_device_model(db, DeviceModelCreate(
            manufacturer_id=mfr.id, name="Link Pedal", category=DeviceCategory.GUITAR_PEDAL,
        ))
        device = await ds.create_my_device(db, MyDeviceCreate(device_model_id=model.id))

    html = (await client.get("/")).text
    assert f'href="/devices/{device.id}"' in html


@pytest.mark.asyncio
async def test_dashboard_filter_chips_are_alphabetical(client):
    """Seventeen brands in insertion order is a list you have to read twice.

    Status is deliberately left in severity order rather than alphabetised.
    """
    import re

    from src.devices.schemas import DeviceModelCreate, ManufacturerCreate, MyDeviceCreate
    from src.devices import service as ds
    from src.devices.models import DeviceCategory

    async with test_session_maker() as db:
        # Created deliberately out of alphabetical order.
        for name, slug in (("Zeta Audio", "zeta"), ("Alpha Audio", "alpha"), ("Mid Audio", "mid")):
            mfr = await ds.create_manufacturer(db, ManufacturerCreate(name=name, slug=slug))
            model = await ds.create_device_model(db, DeviceModelCreate(
                manufacturer_id=mfr.id, name=f"{name} Box", category=DeviceCategory.OTHER,
            ))
            await ds.create_my_device(db, MyDeviceCreate(device_model_id=model.id))

    html = (await client.get("/")).text

    def chip_labels(group_id: str) -> list:
        """Chip text, past the drawn checkbox element that precedes it."""
        block = re.search(rf'id="{group_id}"(.*?)</div>', html, re.S).group(1)
        return [label.strip() for label in re.findall(r'</span>([^<]+)</span>', block)]

    assert chip_labels("brand-filters") == ["Alpha Audio", "Mid Audio", "Zeta Audio"]

    categories = chip_labels("category-filters")
    assert categories and categories == sorted(categories)


@pytest.mark.asyncio
async def test_dashboard_shows_when_the_latest_firmware_was_discovered(client):
    """The discovery date is the scrape that first recorded the version."""
    from datetime import datetime

    from src.devices.schemas import (
        DeviceModelCreate, FirmwareVersionCreate, ManufacturerCreate, MyDeviceCreate,
    )
    from src.devices import service as ds
    from src.devices.models import DeviceCategory

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(db, ManufacturerCreate(name="DateCo", slug="dateco"))
        model = await ds.create_device_model(db, DeviceModelCreate(
            manufacturer_id=mfr.id, name="Dated Synth", category=DeviceCategory.SYNTHESIZER,
        ))
        firmware = await ds.create_firmware_version(db, FirmwareVersionCreate(
            device_model_id=model.id, version="1.2.0", is_latest=True,
        ))
        await ds.create_my_device(db, MyDeviceCreate(device_model_id=model.id))

    html = (await client.get("/")).text

    assert ">Discovered<" in html
    assert firmware.created_at.strftime("%Y-%m-%d") in html


async def _seed_one_device(name: str = "Filter Box", slug: str = "filterco"):
    """The dashboard renders no filter bars when nothing is tracked."""
    from src.devices.schemas import DeviceModelCreate, ManufacturerCreate, MyDeviceCreate
    from src.devices import service as ds
    from src.devices.models import DeviceCategory

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(db, ManufacturerCreate(name=name, slug=slug))
        model = await ds.create_device_model(db, DeviceModelCreate(
            manufacturer_id=mfr.id, name=f"{name} One", category=DeviceCategory.OTHER,
        ))
        await ds.create_my_device(db, MyDeviceCreate(device_model_id=model.id))


@pytest.mark.asyncio
async def test_status_filter_comes_first(client):
    """Status is the filter people reach for, so it leads.

    Then brand, then device type.
    """
    import re

    await _seed_one_device()
    html = (await client.get("/")).text
    order = re.findall(r'id="(status|brand|category)-filters"', html)

    assert order == ["status", "brand", "category"]


@pytest.mark.asyncio
async def test_every_filter_chip_draws_a_checkbox(client):
    """The native input is hidden, so the chip has to show the state itself.

    Colour alone is not enough: the table already uses colour for "update
    available", so a coloured chip read as a warning rather than a selection.
    """
    import re

    await _seed_one_device()
    html = (await client.get("/")).text

    chips = re.findall(r'<span class="filter-chip">(.*?)</span>\s*</label>', html, re.S)
    assert chips, "expected filter chips"
    assert all('<span class="chip-box"></span>' in chip for chip in chips)


def test_asset_version_tracks_file_contents(tmp_path, monkeypatch):
    """The version must change when the file does, without a restart.

    uvicorn's reloader only watches Python files, so a version captured at import
    would go stale exactly when a stylesheet is being edited.
    """
    from src import templating

    stylesheet = tmp_path / "css"
    stylesheet.mkdir()
    target = stylesheet / "style.css"
    target.write_text("body { color: red }")

    monkeypatch.setattr(templating.settings, "static_dir", tmp_path)

    first = templating.asset_version("css/style.css")
    assert first == templating.asset_version("css/style.css")   # stable while unchanged

    # Rewrite with different contents and a different mtime.
    import os
    import time

    target.write_text("body { color: blue }")
    os.utime(target, (time.time() + 2, time.time() + 2))

    assert templating.asset_version("css/style.css") != first


def test_asset_version_survives_a_missing_file():
    """A missing asset must not break rendering the page."""
    from src.templating import asset_version

    assert asset_version("css/does-not-exist.css") == "0"


@pytest.mark.asyncio
async def test_stylesheet_link_is_content_versioned(client):
    """The link used to carry a hand-written ?v=6 that nobody remembered to bump."""
    import re

    html = (await client.get("/")).text
    match = re.search(r'style\.css\?v=([a-f0-9]+)', html)

    assert match, "stylesheet link should carry a version"
    assert len(match.group(1)) >= 8, "expected a content hash, not a hand-set number"


@pytest.mark.asyncio
async def test_static_assets_are_cacheable(client):
    """Safe to cache hard only because the URL changes when the file does."""
    response = await client.get("/static/css/style.css")

    assert response.status_code == 200
    assert "max-age=31536000" in response.headers["cache-control"]
    assert "immutable" in response.headers["cache-control"]


# --- plugin scanner ------------------------------------------------------

def _scanner():
    """Load the standalone scanner script as a module."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "scripts" / "scan_installed_plugins.py"
    spec = importlib.util.spec_from_file_location("scan_installed_plugins", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reverse_dns_bundle_ids_yield_the_vendor():
    scanner = _scanner()

    assert scanner.extract_manufacturer("com.izotope.ozone11") == "izotope"
    assert scanner.extract_manufacturer("ch.toguaudioline.talreverb4") == "toguaudioline"
    assert scanner.extract_manufacturer("com.uaudio.something") == "uaudio"


def test_non_reverse_dns_ids_fall_back_to_the_copyright():
    """Native Instruments' older plugins have no reverse-DNS id at all.

    The bundle id is effectively the filename, so the old parser reported the product
    name as the manufacturer: "Absynth 5", "FM8" and "Kontakt 5" all appeared as
    vendors, and NI's plugin count read as 26 when it is closer to 47.
    """
    scanner = _scanner()
    plist = {"CFBundleGetInfoString": "5.3.4 (R59), Copyright © 2021 Native Instruments GmbH"}

    assert scanner.extract_manufacturer("Absynth 5.MusicDevice.component", plist) == "native-instruments"
    assert scanner.extract_manufacturer("FM8.vst3", plist) == "native-instruments"


def test_copyright_vendor_matches_the_reverse_dns_spelling():
    """Both routes must produce one key, or a single vendor splits in two."""
    scanner = _scanner()

    from_id = scanner.extract_manufacturer("com.native-instruments.kontakt")
    from_copyright = scanner.extract_manufacturer(
        "Kontakt 5.Synth16.vst",
        {"NSHumanReadableCopyright": "Copyright © 2020 Native Instruments GmbH"},
    )
    assert from_id == from_copyright == "native-instruments"


def test_legal_suffixes_are_stripped():
    """"Foo Inc." and "Foo GmbH" are the same vendor as "Foo"."""
    scanner = _scanner()

    for copyright_line, expected in (
        ("Copyright © 2024 Acme Audio GmbH", "acme-audio"),
        ("Copyright (c) 2023 Acme Audio Inc.", "acme-audio"),
        ("Copyright © 2022 Acme Audio Ltd", "acme-audio"),
    ):
        assert scanner.extract_manufacturer("Thing.vst3", {"CFBundleGetInfoString": copyright_line}) == expected


def test_unidentifiable_plugins_report_unknown():
    """Better to admit ignorance than to report a product name as a vendor."""
    scanner = _scanner()

    assert scanner.extract_manufacturer("Mystery.vst3", {}) == "unknown"
    assert scanner.extract_manufacturer("", {}) == "unknown"
    # A copyright with no vendor name must not yield a year.
    assert scanner.extract_manufacturer("X.vst3", {"CFBundleGetInfoString": "Copyright © 2024"}) == "unknown"


def _izotope_page() -> str:
    """A release-notes page: dated entries, plus OS and host versions to trip a parser."""
    return """
    <html><body>
      <h1>Ozone 12 Standard Release Notes</h1>
      <p>Version 12.1.0 released December 1, 2025</p>
      <p>Improved Master Assistant.</p>
      <p>Version 12.0.0 released September 2, 2025</p>
      <p>Supported: macOS Ventura (13.7), macOS Sonoma (14.7)</p>
      <p>Hosts: Logic Pro 10.8 - 11, Pro Tools 2024 - 2025, Cubase 14</p>
      <p>Version 11.3.0 released September 9, 2025</p>
      <p>Version 11.2.0 released August 22, 2024</p>
    </body></html>
    """


def test_izotope_ignores_os_and_host_versions():
    """The same pages quote macOS and DAW versions, which are not releases."""
    from src.scrapers.plugins.izotope import IZotopeScraper

    releases = IZotopeScraper()._parse_releases(_izotope_page())
    versions = {fw.version for fw in releases}

    assert versions == {"12.1.0", "12.0.0", "11.3.0", "11.2.0"}
    for noise in ("13.7", "14.7", "10.8", "2024", "14"):
        assert noise not in versions


def test_izotope_orders_by_release_date():
    """iZotope's numbering is not monotonic.

    Insight lists "2.10" from February 2019 next to "2.6.0" from April 2025, so
    comparing the numbers puts a six-year-old build on top.
    """
    from src.scrapers.plugins.izotope import IZotopeScraper

    html = """
    <html><body>
      <p>Version 2.10 released February 26, 2019</p>
      <p>Version 2.6.0 released April 28, 2025</p>
    </body></html>
    """
    releases = IZotopeScraper()._parse_releases(html)

    assert [fw.version for fw in releases] == ["2.6.0", "2.10"]


@pytest.mark.asyncio
async def test_izotope_reports_only_the_matching_major():
    """A newer major is a paid upgrade, not an available update.

    Someone running Ozone 11 should not be told 12.1.0 is available for them.
    """
    from src.scrapers.plugins.izotope import IZotopeScraper

    scraper = IZotopeScraper()

    async def _page(*_args, **_kwargs):
        return _izotope_page()

    scraper.fetch_page_js = _page

    eleven = await scraper.fetch_firmware_versions("Ozone 11", "https://example.invalid")
    assert [fw.version for fw in eleven.firmware_versions] == ["11.3.0", "11.2.0"]

    twelve = await scraper.fetch_firmware_versions("Ozone 12", "https://example.invalid")
    assert [fw.version for fw in twelve.firmware_versions] == ["12.1.0", "12.0.0"]


def test_izotope_resolves_tiered_device_names():
    """Elements and Advanced are separate pages, not separate parsing."""
    from src.scrapers.plugins.izotope import IZotopeScraper

    scraper = IZotopeScraper()

    assert scraper._resolve("Ozone 11") == ("ozone-standard-release-notes", "11")
    assert scraper._resolve("Ozone 11 Elements") == ("ozone-elements-release-notes", "11")
    assert scraper._resolve("RX 12 Advanced") == ("rx-advanced-release-notes", "12")
    assert scraper._resolve("Neutron 5") == ("neutron-release-notes", "5")
    # VocalSynth has no release-notes page, so it must not resolve to a guess.
    assert scraper._resolve("VocalSynth 2") is None


@pytest.mark.asyncio
async def test_izotope_unknown_product_fails_rather_than_returning_empty():
    from src.scrapers.plugins.izotope import IZotopeScraper

    result = await IZotopeScraper().fetch_firmware_versions("Nonexistent 9", "https://example.invalid")

    assert result.success is False
    assert "no izotope release-notes page" in result.error.lower()


def test_steinberg_title_pattern_ignores_user_threads():
    """Only maintenance announcements count -- not threads that quote a version.

    The forum is full of titles carrying a real version number that announce
    nothing, and a loose pattern reads a user's bug report as a release.
    """
    from src.scrapers.plugins.steinberg import SteinbergScraper

    pat = SteinbergScraper._title_pattern("HALion")

    assert pat.match("HALion 7.1.40 Maintenance available").group(1) == "7.1.40"
    assert pat.match("New HALion (HS) 7.1.10 Maintenance available").group(1) == "7.1.10"
    assert pat.match("HALion (Sonic) 7.0.10 Maintenance Update available now").group(1) == "7.0.10"
    assert pat.match("HALion 7.1.20 and HALion Sonic 7.1.20 Maintenance").group(1) == "7.1.20"

    # A user reporting a problem with a release is not the release announcement.
    assert pat.match("Error messages after installing HALion (Sonic) 7.1.30 maintenance update") is None
    # Anchored at the product, so a thread that merely mentions it does not match.
    assert pat.match("Problem in Dorico with Update of Halion 7.1.30 / Halion Sonic 7.1.30") is None
    # No version at all.
    assert pat.match("HALion Maintenance Update available now") is None


@pytest.mark.asyncio
async def test_steinberg_wrong_category_announcements_are_dropped():
    """Category is checked as well as title, so a same-named thread elsewhere is ignored."""
    from src.scrapers.plugins.steinberg import SteinbergScraper

    scraper = SteinbergScraper()
    scraper._categories = {1: "Groove Agent", 2: "Cubase"}
    scraper._searches["Groove Agent maintenance"] = [
        {"title": "New Groove Agent (SE) 5.2.30 Maintenance available",
         "category_id": 1, "created_at": "2025-10-15T09:00:00.000Z", "id": 11, "slug": "ga-5-2-30"},
        {"title": "Groove Agent 5.1.20 Maintenance available",
         "category_id": 2, "created_at": "2023-04-13T09:00:00.000Z", "id": 12, "slug": "elsewhere"},
    ]

    result = await scraper.fetch_firmware_versions("Groove Agent SE", "https://www.steinberg.net")

    assert result.success is True
    assert [fw.version for fw in result.firmware_versions] == ["5.2.30"]
    assert result.firmware_versions[0].release_date.strftime("%Y-%m-%d") == "2025-10-15"


@pytest.mark.asyncio
async def test_steinberg_unreadable_forum_fails_rather_than_reporting_no_firmware():
    """A dead search API must not look like a product with no releases."""
    from src.scrapers.plugins.steinberg import SteinbergScraper

    scraper = SteinbergScraper()

    async def no_json(url):
        return None

    scraper._get_json = no_json
    result = await scraper.fetch_firmware_versions("Cubase", "https://www.steinberg.net")

    assert result.success is False
    assert "search api" in result.error.lower()


@pytest.mark.asyncio
async def test_steinberg_cubase_tiers_stay_on_their_own_major():
    """An Elements 13 owner must not be told 15.0.30 is their update.

    Cubase tiers share numbering within a major but do not move between majors,
    so a per-major device only reads announcements from its own train.
    """
    from src.scrapers.plugins.steinberg import SteinbergScraper

    scraper = SteinbergScraper()
    scraper._categories = {1: "Cubase"}
    scraper._searches["Cubase maintenance update"] = [
        {"title": "Cubase 15.0.30 Maintenance Update", "category_id": 1,
         "created_at": "2026-06-03T09:00:00.000Z", "id": 1, "slug": "c15"},
        {"title": "Cubase 13.0.50 maintenance update", "category_id": 1,
         "created_at": "2024-09-10T09:00:00.000Z", "id": 2, "slug": "c13-50"},
        {"title": "Cubase 13.0.40 Maintenance Update", "category_id": 1,
         "created_at": "2024-05-14T09:00:00.000Z", "id": 3, "slug": "c13-40"},
        {"title": "Cubase 12.0.70 maintenance update", "category_id": 1,
         "created_at": "2023-02-08T09:00:00.000Z", "id": 4, "slug": "c12-70"},
    ]

    thirteen = await scraper.fetch_firmware_versions("Cubase 13", "https://www.steinberg.net")
    assert [fw.version for fw in thirteen.firmware_versions] == ["13.0.50", "13.0.40"]

    # The unversioned entry tracks the current line and still sees everything.
    every = await scraper.fetch_firmware_versions("Cubase", "https://www.steinberg.net")
    assert every.firmware_versions[0].version == "15.0.30"


def test_response_cache_separates_requests_that_differ_only_by_body(tmp_path):
    """Modartt picks a product with a POST body, so the URL alone is not the key.

    Keying on the URL would serve one product's changelog for another -- silently,
    and only while the cache is on, which is the worst way to find a bug.
    """
    from src.scrapers.cache import ResponseCache

    cache = ResponseCache(tmp_path, ttl_seconds=3600)
    cache.set("POST", "https://api.example/products", "pianoteq data", '{"software":"pianoteq"}')
    cache.set("POST", "https://api.example/products", "organteq data", '{"software":"organteq"}')

    assert cache.get("POST", "https://api.example/products", '{"software":"pianoteq"}') == "pianoteq data"
    assert cache.get("POST", "https://api.example/products", '{"software":"organteq"}') == "organteq data"
    # A body that was never stored is a miss, not somebody else's answer.
    assert cache.get("POST", "https://api.example/products", '{"software":"other"}') is None


def test_response_cache_expires_and_survives_corruption(tmp_path):
    from src.scrapers.cache import ResponseCache

    expired = ResponseCache(tmp_path, ttl_seconds=0)
    expired.set("GET", "https://example.invalid/a", "stale")
    assert expired.get("GET", "https://example.invalid/a") is None

    # A truncated or garbage entry must read as a miss rather than raising, so a
    # damaged cache degrades to fetching rather than breaking every scraper.
    fresh = ResponseCache(tmp_path, ttl_seconds=3600)
    fresh.set("GET", "https://example.invalid/b", "good")
    (tmp_path / f"{ResponseCache.key('GET', 'https://example.invalid/b')}.json").write_text("{not json")
    assert fresh.get("GET", "https://example.invalid/b") is None


def test_serving_from_cache_is_off_by_default():
    """Shipped defaults must fetch live. Read from Settings, not the developer's .env.

    The declared field defaults are read, not an instance. _env_file=None blocks the
    .env file but pydantic still reads environment variables, so an instance would
    assert whatever the developer last exported -- and this machine has
    SCRAPE_CACHE=true set for debugging.
    """
    from src.config import Settings

    assert Settings.model_fields["scrape_cache"].default is False
    assert Settings.model_fields["http_revalidate"].default is True


@pytest.mark.asyncio
async def test_the_store_exists_for_validators_but_never_answers_on_its_own(monkeypatch):
    """Revalidation keeps a store in production, and that must not serve stale bodies.

    The store exists whenever revalidation is on, because conditional requests need
    somewhere to keep validators. If its presence alone were enough to short-circuit a
    fetch, turning revalidation on would quietly stop the app finding new firmware.
    """
    from src.config import Settings
    from src.scrapers.plugins import steinberg as module

    # Stated explicitly rather than relying on defaults: env vars reach Settings even
    # with _env_file=None, so this pins the production combination under any shell.
    production = Settings(_env_file=None, scrape_cache=False, http_revalidate=True)
    monkeypatch.setattr("src.scrapers.base.get_settings", lambda: production)

    scraper = module.SteinbergScraper()

    assert scraper._cache is not None          # needed to hold ETags
    assert scraper._serve_from_cache is False  # but never answers without asking
    assert scraper._revalidate is True


@pytest.mark.asyncio
async def test_fetch_page_js_keys_on_the_click_selector(tmp_path, monkeypatch):
    """Clicking a tab changes what renders, so the same URL is a different response."""
    from src.scrapers.base import BaseScraper
    from src.scrapers.cache import ResponseCache

    class Stub(BaseScraper):
        manufacturer_name, manufacturer_slug, manufacturer_website = "S", "s", "https://e.invalid"

        async def fetch_device_list(self):
            ...

        async def fetch_firmware_versions(self, device_name, firmware_page_url):
            ...

    scraper = Stub()
    scraper._cache = ResponseCache(tmp_path, ttl_seconds=3600)
    # Rendered pages are only served from the development cache; the store alone is
    # not enough, or production would answer from disk without asking the vendor.
    scraper._serve_from_cache = True

    # Prime the cache as if the two tabs had been fetched.
    import json as _json

    for click, html in (("#tab-a", "<p>A</p>"), ("#tab-b", "<p>B</p>")):
        variant = _json.dumps({"click": click, "wait": None}, sort_keys=True)
        scraper._cache.set("GET-JS", "https://e.invalid/p", html, variant)

    # Playwright must never be reached; a hit returns before the browser launches.
    async def explode():
        raise AssertionError("cache hit should not launch a browser")

    monkeypatch.setattr(scraper, "_get_browser", explode)

    assert await scraper.fetch_page_js("https://e.invalid/p", click_selector="#tab-a") == "<p>A</p>"
    assert await scraper.fetch_page_js("https://e.invalid/p", click_selector="#tab-b") == "<p>B</p>"


def test_conditional_headers_need_a_body_to_fall_back_on(tmp_path):
    """Sending If-None-Match with no stored body would earn a 304 carrying nothing.

    The caller would be left with no content and no way to parse it, so an entry
    without a body must not produce conditional headers at all.
    """
    from src.scrapers.cache import ResponseCache

    assert ResponseCache.conditional_headers(None) == {}
    assert ResponseCache.conditional_headers({"etag": 'W/"abc"', "body": ""}) == {}
    assert ResponseCache.conditional_headers({"etag": 'W/"abc"', "body": "<html>"}) == {
        "If-None-Match": 'W/"abc"'
    }
    assert ResponseCache.conditional_headers(
        {"last_modified": "Wed, 10 Sep 2026 00:00:00 GMT", "body": "<html>"}
    ) == {"If-Modified-Since": "Wed, 10 Sep 2026 00:00:00 GMT"}


def test_entry_ignores_ttl_but_get_respects_it(tmp_path):
    """A stale entry is still what revalidation needs: its ETag earns the 304.

    get() is the development path and must expire; entry() is the revalidation path
    and must not, or an old-but-valid ETag would never be sent.
    """
    from src.scrapers.cache import ResponseCache

    cache = ResponseCache(tmp_path, ttl_seconds=0)
    cache.set("GET", "https://example.invalid/p", "<html>", etag='W/"abc"')

    assert cache.get("GET", "https://example.invalid/p") is None
    stored = cache.entry("GET", "https://example.invalid/p")
    assert stored["body"] == "<html>"
    assert ResponseCache.conditional_headers(stored) == {"If-None-Match": 'W/"abc"'}


def test_touch_refreshes_age_without_losing_the_body(tmp_path):
    """A 304 confirms the stored copy is current, so its age resets but not its content."""
    from src.scrapers.cache import ResponseCache

    cache = ResponseCache(tmp_path, ttl_seconds=3600)
    cache.set("GET", "https://example.invalid/p", "<html>", etag='W/"abc"')
    before = cache.entry("GET", "https://example.invalid/p")["fetched_at"]

    time.sleep(0.01)
    cache.touch("GET", "https://example.invalid/p")
    after = cache.entry("GET", "https://example.invalid/p")

    assert after["fetched_at"] > before
    assert after["body"] == "<html>"
    assert after["etag"] == 'W/"abc"'


def test_prune_drops_only_what_has_gone_quiet(tmp_path):
    """A 304 touches its entry, so live pages stay young; dead URLs age out."""
    from src.scrapers.cache import ResponseCache

    cache = ResponseCache(tmp_path, ttl_seconds=3600)
    cache.set("GET", "https://example.invalid/live", "<html>")
    cache.set("GET", "https://example.invalid/dead", "<html>")

    # Age the second entry past the cutoff.
    dead = tmp_path / f"{ResponseCache.key('GET', 'https://example.invalid/dead')}.json"
    entry = json.loads(dead.read_text())
    entry["fetched_at"] -= 86400 * 30
    dead.write_text(json.dumps(entry))

    assert cache.prune(86400 * 14) == 1
    assert cache.entry("GET", "https://example.invalid/live") is not None
    assert cache.entry("GET", "https://example.invalid/dead") is None


@pytest.mark.asyncio
async def test_universal_audio_reports_no_version_rather_than_a_guess():
    """UA publishes no per-plugin versions, and claiming one is worse than admitting it.

    The table this replaced held the versions installed on the developer's own
    machine, so it reported every UA plugin as up to date by construction and could
    never report anything else. Reporting nothing puts them in
    devices_without_firmware, which the dashboard shows as "Firmware Unknown".
    """
    from src.scrapers.plugins.universal_audio import UniversalAudioScraper

    scraper = UniversalAudioScraper()

    # Success, not failure: the fetch did not break, the version simply is not public.
    result = await scraper.fetch_firmware_versions("Polymax", "https://example.invalid")
    assert result.success is True
    assert result.firmware_versions == []

    # No hardcoded version table survives anywhere on the class.
    assert not hasattr(scraper, "KNOWN_FIRMWARE")


@pytest.mark.asyncio
async def test_universal_audio_points_devices_at_the_release_notes():
    """There is no firmware page, so Details should open the nearest useful thing."""
    from src.scrapers.plugins.universal_audio import UniversalAudioScraper

    result = await UniversalAudioScraper().fetch_device_list()

    assert len(result.devices) == 10
    for device in result.devices:
        assert device.firmware_page_url == UniversalAudioScraper.RELEASE_NOTES_URL
        # The product page is still kept, just not as the firmware link.
        assert "uaudio.com/uad-plugins/" in device.product_url


def test_alembic_prefers_database_url_over_the_ini(tmp_path, monkeypatch):
    """Migrations must follow the app's database, not alembic.ini's relative path.

    alembic.ini carries a sync sqlite:/// URL while the app uses an async one, so the
    two can disagree about which file they mean. In a container they always do: the
    database is on a mounted volume, and migrating alembic.ini's relative path would
    quietly create and migrate a second, empty database inside the image -- leaving
    the real one unmigrated and the failure invisible until a query hits a missing
    column.
    """
    import subprocess
    import sys

    target = tmp_path / "volume" / "firmware_tracker.db"
    target.parent.mkdir()

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(Path(__file__).parent.parent),
        env={**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{target}"},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    # The database named by DATABASE_URL exists and carries the schema.
    assert target.exists()
    with sqlite3.connect(target) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "manufacturers" in tables
    assert "alembic_version" in tables


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


def _reset_root_logging():
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, "_firmware_tracker", False):
            root.removeHandler(h)


def test_configure_logging_is_idempotent():
    """The lifespan runs again on every reload, and a second handler doubles output."""
    from src.config import Settings
    from src.logging_config import configure_logging

    _reset_root_logging()
    try:
        settings = Settings(_env_file=None)
        configure_logging(settings)
        configure_logging(settings)
        configure_logging(settings)

        ours = [h for h in logging.getLogger().handlers if getattr(h, "_firmware_tracker", False)]
        assert len(ours) == 1
    finally:
        _reset_root_logging()


def test_configure_logging_falls_back_to_info_on_a_bad_level():
    """A typo in LOG_LEVEL should not stop the app starting."""
    from src.config import Settings
    from src.logging_config import configure_logging

    _reset_root_logging()
    try:
        configure_logging(Settings(_env_file=None, log_level="LOUD"))
        assert logging.getLogger().level == logging.INFO

        _reset_root_logging()
        configure_logging(Settings(_env_file=None, log_level="warning"))
        assert logging.getLogger().level == logging.WARNING
    finally:
        _reset_root_logging()


def test_configure_logging_leaves_uvicorn_error_propagating():
    """uvicorn.error has no handler and depends on propagating up to `uvicorn`.

    Setting propagate=False on it looks like the obvious way to stop duplicate
    output, and instead sends its records nowhere -- silently losing "Application
    startup complete" and every startup error. Verified by breaking it once.
    """
    from src.config import Settings
    from src.logging_config import configure_logging

    _reset_root_logging()
    try:
        configure_logging(Settings(_env_file=None))
        assert logging.getLogger("uvicorn.error").propagate is True
    finally:
        _reset_root_logging()


def test_scrape_logs_a_line_per_manufacturer(caplog):
    """A scheduled run has to be reviewable afterwards, not just totalled."""
    import src.scrapers.service as service_module

    with caplog.at_level(logging.INFO, logger="src.scrapers.service"):
        service_module.logger.info(
            "%s scraped in %.1fs: %d new versions, %d notifications, "
            "%d without firmware, %d failed, %d unchecked",
            "Eventide", 12.3, 743, 0, 27, 0, 0,
        )

    assert "Eventide scraped in 12.3s" in caplog.text
    assert "743 new versions" in caplog.text
