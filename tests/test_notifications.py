import pytest

from tests.support import test_session_maker


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
