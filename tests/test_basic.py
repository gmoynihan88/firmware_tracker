import pytest

from src.database import get_db
from src.main import app


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
    assert "arturia" in data["scrapers"]
    assert "korg" in data["scrapers"]
    assert "novation" in data["scrapers"]
    assert "ableton" in data["scrapers"]
    assert "teenageengineering" in data["scrapers"]
    assert "akai" in data["scrapers"]
    assert "iconnectivity" in data["scrapers"]
    assert "keithmcmillen" in data["scrapers"]
    assert "empress" in data["scrapers"]
    assert "fender" in data["scrapers"]
    assert "kemper" in data["scrapers"]
    assert "fractal" in data["scrapers"]
    assert "neuraldsp" in data["scrapers"]
    assert "zoom" in data["scrapers"]
    assert "bitwig" in data["scrapers"]
    assert "pspaudioware" in data["scrapers"]
    assert "fabfilter" in data["scrapers"]
    assert "valhalla" in data["scrapers"]
    assert "uhe" in data["scrapers"]
    assert "kilohearts" in data["scrapers"]
    assert "goodhertz" in data["scrapers"]
    assert "xfer" in data["scrapers"]
    assert "cableguys" in data["scrapers"]
    assert "soundtoys" in data["scrapers"]
    assert "tokyodawn" in data["scrapers"]
    assert "klanghelm" in data["scrapers"]
    assert "positivegrid" in data["scrapers"]
    assert "cockos" in data["scrapers"]
    assert "imageline" in data["scrapers"]
    assert "rme" in data["scrapers"]
    assert "obsproject" in data["scrapers"]
    assert "avid" in data["scrapers"]
    assert "apple" in data["scrapers"]
    assert "waves" in data["scrapers"]
    assert "pioneerdj" in data["scrapers"]
    assert "nord" in data["scrapers"]
    assert "enginedj" in data["scrapers"]
    assert "presonus" in data["scrapers"]
    assert "sequential" in data["scrapers"]
    assert "polyend" in data["scrapers"]
    assert "toontrack" in data["scrapers"]
    assert "motu" in data["scrapers"]
    assert "headrush" in data["scrapers"]
    assert "hotone" in data["scrapers"]
    assert "serato" in data["scrapers"]
    assert "oberheim" in data["scrapers"]
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


@pytest.mark.asyncio
async def test_health_endpoints_stay_reachable_when_auth_is_on(auth_enabled, client):
    """A load balancer cannot present credentials."""
    assert (await client.get("/health")).status_code == 200
    assert (await client.get("/health/ready")).status_code == 200
