import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app
from src.database import init_db, engine, Base


@pytest.fixture(autouse=True)
async def setup_db():
    """Set up test database."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
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
