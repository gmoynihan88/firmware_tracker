import pytest

from tests.support import _seed_notification, test_session_maker


@pytest.mark.asyncio
async def test_manufacturer_crud_round_trip(client):
    created = await client.post("/api/manufacturers", json={
        "name": "Roundtrip Audio", "slug": "roundtrip", "website_url": "https://example.invalid",
    })
    assert created.status_code == 201
    mid = created.json()["id"]

    assert (await client.get(f"/api/manufacturers/{mid}")).json()["name"] == "Roundtrip Audio"
    assert any(m["id"] == mid for m in (await client.get("/api/manufacturers")).json())

    patched = await client.patch(f"/api/manufacturers/{mid}", json={"name": "Renamed Audio"})
    assert patched.status_code == 200
    assert patched.json()["name"] == "Renamed Audio"
    # A patch must not clear the fields it did not mention.
    assert patched.json()["slug"] == "roundtrip"

    assert (await client.delete(f"/api/manufacturers/{mid}")).status_code == 204
    assert (await client.get(f"/api/manufacturers/{mid}")).status_code == 404


@pytest.mark.asyncio
async def test_device_model_crud_round_trip(client):
    mfr = (await client.post("/api/manufacturers", json={"name": "M", "slug": "m"})).json()

    created = await client.post("/api/device-models", json={
        "manufacturer_id": mfr["id"], "name": "Thing One", "category": "guitar_pedal",
    })
    assert created.status_code == 201
    did = created.json()["id"]

    detail = await client.get(f"/api/device-models/{did}")
    assert detail.status_code == 200
    # The detail view joins the manufacturer, which the list schema also carries.
    assert detail.json()["manufacturer"]["slug"] == "m"

    patched = await client.patch(f"/api/device-models/{did}", json={"name": "Thing Two"})
    assert patched.json()["name"] == "Thing Two"

    assert (await client.delete(f"/api/device-models/{did}")).status_code == 204
    assert (await client.get(f"/api/device-models/{did}")).status_code == 404


@pytest.mark.asyncio
async def test_device_models_can_be_filtered_by_manufacturer(client):
    first = (await client.post("/api/manufacturers", json={"name": "A", "slug": "a"})).json()
    second = (await client.post("/api/manufacturers", json={"name": "B", "slug": "b"})).json()
    for mfr, name in ((first, "A1"), (first, "A2"), (second, "B1")):
        await client.post("/api/device-models", json={
            "manufacturer_id": mfr["id"], "name": name, "category": "other",
        })

    only_a = await client.get(f"/api/device-models?manufacturer_id={first['id']}")
    assert sorted(d["name"] for d in only_a.json()) == ["A1", "A2"]


@pytest.mark.asyncio
async def test_my_device_crud_round_trip(client):
    mfr = (await client.post("/api/manufacturers", json={"name": "M", "slug": "m"})).json()
    model = (await client.post("/api/device-models", json={
        "manufacturer_id": mfr["id"], "name": "Tracked", "category": "synthesizer",
    })).json()

    created = await client.post("/api/my-devices", json={
        "device_model_id": model["id"], "nickname": "Studio unit",
        "current_firmware_version": "1.0.0",
    })
    assert created.status_code == 201
    mine = created.json()["id"]

    assert (await client.get(f"/api/my-devices/{mine}")).json()["nickname"] == "Studio unit"

    patched = await client.patch(f"/api/my-devices/{mine}", json={"current_firmware_version": "1.1.0"})
    assert patched.json()["current_firmware_version"] == "1.1.0"
    assert patched.json()["nickname"] == "Studio unit"

    assert (await client.delete(f"/api/my-devices/{mine}")).status_code == 204
    assert (await client.get(f"/api/my-devices/{mine}")).status_code == 404


@pytest.mark.asyncio
async def test_missing_records_are_404_not_500(client):
    """Every by-id route must say not found rather than raising."""
    for path in ("/api/manufacturers/9999", "/api/device-models/9999", "/api/my-devices/9999"):
        response = await client.get(path)
        assert response.status_code == 404, path

    for path in ("/api/manufacturers/9999", "/api/device-models/9999", "/api/my-devices/9999"):
        assert (await client.patch(path, json={"name": "x"})).status_code == 404, path
        assert (await client.delete(path)).status_code == 404, path


@pytest.mark.asyncio
async def test_notification_count_and_read_flow(client):
    note_id = await _seed_notification()

    assert (await client.get("/api/notifications/count")).json()["unread_count"] == 1
    assert len((await client.get("/api/notifications?unread_only=true")).json()) == 1

    assert (await client.post(f"/api/notifications/{note_id}/read")).status_code == 204

    assert (await client.get("/api/notifications/count")).json()["unread_count"] == 0
    # Read notifications are still listed, just not counted.
    assert len((await client.get("/api/notifications")).json()) == 1
    assert (await client.get("/api/notifications?unread_only=true")).json() == []


@pytest.mark.asyncio
async def test_marking_a_missing_notification_read_is_404(client):
    assert (await client.post("/api/notifications/9999/read")).status_code == 404


@pytest.mark.asyncio
async def test_read_all_clears_the_count(client):
    await _seed_notification("2.0.0", slug="notify-one")
    await _seed_notification("3.0.0", slug="notify-two")
    assert (await client.get("/api/notifications/count")).json()["unread_count"] == 2

    assert (await client.post("/api/notifications/read-all")).status_code == 204
    assert (await client.get("/api/notifications/count")).json()["unread_count"] == 0


@pytest.mark.asyncio
async def test_firmware_versions_are_listed_for_a_device_model(client):
    from src.devices import service as ds
    from src.devices.models import DeviceCategory
    from src.devices.schemas import DeviceModelCreate, FirmwareVersionCreate, ManufacturerCreate

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(db, ManufacturerCreate(name="FW Co", slug="fwco"))
        model = await ds.create_device_model(db, DeviceModelCreate(
            manufacturer_id=mfr.id, name="FW Box", category=DeviceCategory.OTHER,
        ))
        for version, latest in (("1.0.0", False), ("1.1.0", True)):
            await ds.create_firmware_version(db, FirmwareVersionCreate(
                device_model_id=model.id, version=version, is_latest=latest,
            ))
        model_id = model.id

    listed = await client.get(f"/api/device-models/{model_id}/firmware")
    assert listed.status_code == 200
    assert {f["version"] for f in listed.json()} == {"1.0.0", "1.1.0"}

    assert (await client.get("/api/device-models/9999/firmware")).status_code == 404
