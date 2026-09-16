"""The catalogue, readable without a password when PUBLIC_CATALOG is set.

The point is a link worth sharing: 2,000 products with their firmware history is the
part of this app worth showing anyone. What must never follow it out is anything about
the person running it -- which devices they own, what they have been notified about --
or any ability to change something.
"""
import contextlib

import pytest
from sqlalchemy import event

from tests.support import test_engine, test_session_maker


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


@contextlib.contextmanager
def _captured_sql():
    """Every statement the app issues while inside the block."""
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(test_engine.sync_engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", record)


@pytest.mark.asyncio
async def test_a_visitor_does_not_pay_for_the_owners_import_panel(public_catalog, client):
    """The import panel's queries do not run for someone who cannot see it.

    Three of them -- device counts per vendor, the last successful scrape per scraper,
    and every vendor's website -- existed only to fill a panel the template renders
    behind an authenticated check. /catalog is the public, cached, most requested page
    here, which made them the most-run queries in the app that nobody read.

    Pinned on scrape_runs because nothing else on this page touches that table, so its
    absence means precisely one thing. The owner's request is checked in the same test:
    "no query ran" is also what a page that stopped working looks like, and asserting
    only the absence would pass for that reason too.
    """
    await _seed_tracked_device()

    with _captured_sql() as anonymous:
        visitor = await client.get("/catalog", headers={"accept": "text/html"})
    assert visitor.status_code == 200

    assert anonymous, "no SQL captured at all -- the listener never attached"
    assert not [sql for sql in anonymous if "scrape_runs" in sql], \
        "a visitor paid for the owner's import panel"

    await client.post("/login", data={"password": "correct horse"})

    with _captured_sql() as owner:
        owned = await client.get("/catalog", headers={"accept": "text/html"})
    assert owned.status_code == 200

    assert [sql for sql in owner if "scrape_runs" in sql], \
        "the owner's import panel stopped being built"


@pytest.mark.asyncio
async def test_the_login_page_offers_the_catalogue_when_there_is_one(public_catalog, client):
    """Somewhere to go other than a password prompt, when there is somewhere to go.

    The other half of this is in test_auth: with the catalogue private, the same page
    must not offer it. Together they pin the condition rather than one state of it.
    """
    import re

    page = (await client.get("/login", headers={"accept": "text/html"})).text
    card = re.search(r'<form class="login-card".*?</form>', page, re.S)
    assert card, "no login card rendered"

    # Scoped to the card, for the same reason as its counterpart in test_auth: the nav
    # links /catalog on every page, so checking the whole document would pass even with
    # the conditional block deleted. This one has to fail if the offer disappears.
    assert 'href="/catalog"' in card.group(0)
    assert "https://github.com/gmoynihan88/firmware_tracker" in card.group(0)


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
    # An anonymous page carries no data-tracked at all -- there is no Hide tracked box to
    # feed, so 2,045 copies of "no" were weight with nothing reading them. Absent is also
    # a stronger guarantee than always-"no": there is no attribute left to leak a yes.
    assert "data-tracked" not in anonymous.text
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
async def test_visitors_are_not_shown_operator_controls(public_catalog, client):
    """The import panel posts a scrape, which is a write: for a visitor it could only
    bounce them to a login page, and it presents the vendor list as something to act on."""
    await _seed_tracked_device()

    anonymous = (await client.get("/catalog", headers={"accept": "text/html"})).text

    assert "import-panel" not in anonymous
    assert "/catalog/scrape/" not in anonymous
    assert "Import Devices" not in anonymous
    assert "Import and browse" not in anonymous
    # Still the catalogue, just without the controls.
    assert "Sharable One" in anonymous
    assert "Device Catalog" in anonymous


@pytest.mark.asyncio
async def test_the_owner_still_has_the_import_panel(public_catalog, client):
    await client.post("/login", data={"password": "correct horse"})

    owner = (await client.get("/catalog", headers={"accept": "text/html"})).text

    assert "import-panel" in owner
    assert "/catalog/scrape/" in owner


@pytest.mark.asyncio
async def test_the_navigation_offers_a_way_in_and_nothing_else(public_catalog, client):
    anonymous = (await client.get("/catalog", headers={"accept": "text/html"})).text

    # Asserted on the hrefs: the link text sits on its own line after an SVG, so
    # ">Dashboard<" never appears either way and would pass whatever the nav rendered.
    assert 'href="/login"' in anonymous
    assert 'href="/notifications"' not in anonymous
    assert 'href="/" class="nav-link"' not in anonymous
    assert "notification-badge" not in anonymous
    # Nor a way out of a session they do not have.
    assert 'href="/logout"' not in anonymous
