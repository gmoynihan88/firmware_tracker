"""Reconcile notifications against current state.

Notifications were only ever created at discovery time -- when a scrape added a
firmware version that was not already in the database. That misses the common case:
if a device's installed version is recorded *after* its latest version is already
known, nothing changes during the next scrape, so nothing fires and the device sits
silently behind. TAL-J-8 was a real instance, sitting on 2.0.5 against a known 2.0.6
with no notification, because the version had been in the database all along.

This compares every tracked device against the latest firmware known for its model
and fills in the notifications that were never raised.
"""
import logging
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.devices import service as device_service
from src.devices.models import Notification
from src.devices.schemas import NotificationCreate
from src.notifications.transport import get_notifier

logger = logging.getLogger(__name__)


def _version_key(version: str) -> tuple:
    """Parse a version into a comparable tuple: '9.2.10' -> (9, 2, 10)."""
    import re

    parts = re.findall(r"\d+", version or "")
    return tuple(int(p) for p in parts) if parts else (0,)


def is_behind(installed: str, latest: str) -> bool:
    """Whether `installed` is genuinely older than `latest`.

    Compared numerically rather than by string inequality, so a device running a
    build newer than the manufacturer publishes is not reported as needing an
    update. That happens in practice -- a hotfix that never reached the vendor's
    published version list.
    """
    if not installed or not latest:
        return False
    return _version_key(installed) < _version_key(latest)


async def _already_notified(
    db: AsyncSession, my_device_id: int, firmware_version_id: int
) -> bool:
    """Whether this device was already told about this exact version."""
    result = await db.execute(
        select(Notification.id)
        .where(Notification.my_device_id == my_device_id)
        .where(Notification.firmware_version_id == firmware_version_id)
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def reconcile_notifications(db: AsyncSession) -> dict:
    """Raise notifications for tracked devices behind their latest known firmware.

    Idempotent: a device is notified once per firmware version, so this is safe to
    run after every scrape and on a schedule.
    """
    notifier = get_notifier(get_settings())

    created: List[str] = []
    skipped_no_installed = 0

    for my_device in await device_service.get_my_devices(db):
        if not my_device.notify_on_update:
            continue

        if not my_device.current_firmware_version:
            # Without a known installed version there is nothing to compare against;
            # the device is not behind, it is simply unrecorded.
            skipped_no_installed += 1
            continue

        latest = await device_service.get_latest_firmware(db, my_device.device_model_id)
        if not latest or not is_behind(my_device.current_firmware_version, latest.version):
            continue

        if await _already_notified(db, my_device.id, latest.id):
            continue

        device_model = await device_service.get_device_model(db, my_device.device_model_id)
        name = my_device.nickname or device_model.name
        title = f"New firmware available: {device_model.name} v{latest.version}"
        message = (
            f"A new firmware version ({latest.version}) is available for your {name}. "
            f"You are on {my_device.current_firmware_version}."
        )

        await device_service.create_notification(
            db,
            NotificationCreate(
                my_device_id=my_device.id,
                firmware_version_id=latest.id,
                title=title,
                message=message,
            ),
        )
        created.append(f"{device_model.name} {my_device.current_firmware_version} -> {latest.version}")

        # As elsewhere, delivery is a side effect of the record and cannot fail it.
        await notifier.send(title, message, url=latest.download_url)

    if created:
        logger.info("Reconciled %d missing notification(s): %s", len(created), created)

    return {
        "notifications_created": len(created),
        "devices_notified": created,
        "devices_without_installed_version": skipped_no_installed,
    }
