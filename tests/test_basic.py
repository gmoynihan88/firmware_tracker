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
