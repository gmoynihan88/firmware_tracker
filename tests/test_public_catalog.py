"""The catalogue, readable without a password when PUBLIC_CATALOG is set.

The point is a link worth sharing: 2,000 products with their firmware history is the
part of this app worth showing anyone. What must never follow it out is anything about
the person running it -- which devices they own, what they have been notified about --
or any ability to change something.
"""
import pytest

from tests.support import test_session_maker


@pytest.fixture
def public_catalog(auth_enabled):
    """Authentication on, catalogue public: the configuration a shared link needs."""
    auth_enabled.public_catalog = True
    try:
        yield auth_enabled
    finally:
        auth_enabled.public_catalog = False


async def _seed_tracked_device():
    """A catalogue with one product, tracked by the owner."""
    from src.devices import service as ds
    from src.devices.models import DeviceCategory
    from src.devices.schemas import (
        DeviceModelCreate, FirmwareVersionCreate, ManufacturerCreate, MyDeviceCreate,
    )

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(db, ManufacturerCreate(name="Sharable Audio", slug="sharable"))
        model = await ds.create_device_model(db, DeviceModelCreate(
            manufacturer_id=mfr.id, name="Sharable One", category=DeviceCategory.SYNTHESIZER,
        ))
        await ds.create_firmware_version(db, FirmwareVersionCreate(
            device_model_id=model.id, version="2.1.0", is_latest=True,
        ))
        await ds.create_my_device(db, MyDeviceCreate(device_model_id=model.id))
        return model.id


@pytest.mark.asyncio
async def test_catalogue_is_readable_without_a_password(public_catalog, client):
    response = await client.get("/catalog", headers={"accept": "text/html"})

    assert response.status_code == 200
    assert "Sharable One" not in response.text  # nothing seeded yet, but the page renders
    assert "Device Catalog" in response.text


@pytest.mark.asyncio
async def test_catalogue_stays_private_until_it_is_turned_on(auth_enabled, client):
    """The default: a local install is nobody else's business."""
    assert auth_enabled.public_catalog is False

    response = await client.get("/catalog", headers={"accept": "text/html"})

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


@pytest.mark.asyncio
async def test_a_shared_link_to_the_root_lands_on_the_catalogue(public_catalog, client):
    """A password prompt is a poor thing to send someone."""
    response = await client.get("/", headers={"accept": "text/html"})

    assert response.status_code == 303
    assert response.headers["location"] == "/catalog"


@pytest.mark.asyncio
async def test_the_owners_own_pages_stay_closed(public_catalog, client):
    """Everything that describes the installation rather than the products."""
    for path in ("/", "/notifications", "/devices/add"):
        response = await client.get(path, headers={"accept": "text/html"})
        assert response.status_code == 303, path
        assert response.headers["location"] in ("/login", "/catalog"), path

    for path in ("/api/my-devices", "/api/notifications", "/api/notifications/count",
                 "/partials/notification-badge", "/api/firmware/runs"):
        response = await client.get(path)
        assert response.status_code == 401, path


@pytest.mark.asyncio
async def test_writes_stay_closed(public_catalog, client):
    """Read-only means read-only: the method check is what enforces it."""
    assert (await client.post("/api/my-devices", json={"device_model_id": 1})).status_code == 401
    assert (await client.post("/api/firmware/scrape-all")).status_code == 401
    assert (await client.post("/api/manufacturers", json={"name": "X", "slug": "x"})).status_code == 401
    assert (await client.delete("/api/device-models/1")).status_code == 401

    scrape = await client.post("/catalog/scrape/korg", headers={"accept": "text/html"})
    assert scrape.status_code == 303 and scrape.headers["location"] == "/login"


@pytest.mark.asyncio
async def test_anonymous_visitors_cannot_see_which_devices_are_owned(public_catalog, client):
    """The catalogue marks tracked products; that is a list of someone's gear."""
    await _seed_tracked_device()

    anonymous = await client.get("/catalog", headers={"accept": "text/html"})

    assert anonymous.status_code == 200
    assert "Sharable One" in anonymous.text
    # Every row still carries data-tracked, which is the client-side filter's hook; what
    # matters is that it never says yes, and that nothing on the page discloses ownership.
    assert 'data-tracked="yes"' not in anonymous.text
    assert "tracked-flag" not in anonymous.text
    assert "Hide tracked" not in anonymous.text
    assert "/devices/add?model_id=" not in anonymous.text


@pytest.mark.asyncio
async def test_the_owner_still_sees_the_tracking_controls(public_catalog, client):
    await _seed_tracked_device()
    await client.post("/login", data={"password": "correct horse"})

    owner = await client.get("/catalog", headers={"accept": "text/html"})

    assert "&#10003; tracked" in owner.text or "✓ tracked" in owner.text
    assert "Hide tracked" in owner.text


@pytest.mark.asyncio
async def test_the_version_history_popup_and_read_only_apis_are_public(public_catalog, client):
    model_id = await _seed_tracked_device()

    assert (await client.get(f"/catalog/versions/{model_id}")).status_code == 200
    assert (await client.get("/api/device-models")).status_code == 200
    assert (await client.get("/api/manufacturers")).status_code == 200
    assert (await client.get(f"/api/device-models/{model_id}")).status_code == 200


@pytest.mark.asyncio
async def test_the_navigation_offers_a_way_in_and_nothing_else(public_catalog, client):
    anonymous = (await client.get("/catalog", headers={"accept": "text/html"})).text

    # Asserted on the hrefs: the link text sits on its own line after an SVG, so
    # ">Dashboard<" never appears either way and would pass whatever the nav rendered.
    assert 'href="/login"' in anonymous
    assert 'href="/notifications"' not in anonymous
    assert 'href="/" class="nav-link"' not in anonymous
    assert "notification-badge" not in anonymous
