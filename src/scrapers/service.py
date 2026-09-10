import asyncio
import time

from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Tuple
from datetime import datetime

from src.scrapers.registry import ScraperRegistry
from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult
from src.config import get_settings
from src.devices import service as device_service
from src.notifications.reconcile import is_behind
from src.notifications.transport import get_notifier
from src.devices.schemas import (
    ManufacturerCreate,
    ManufacturerUpdate,
    DeviceModelCreate,
    DeviceModelUpdate,
    FirmwareVersionCreate,
    NotificationCreate,
)
from src.devices.models import DeviceCategory


def map_category(category_str: str) -> DeviceCategory:
    """Map scraper category string to DeviceCategory enum."""
    mapping = {
        "guitar_pedal": DeviceCategory.GUITAR_PEDAL,
        "audio_interface": DeviceCategory.AUDIO_INTERFACE,
        "synthesizer": DeviceCategory.SYNTHESIZER,
        "midi_controller": DeviceCategory.MIDI_CONTROLLER,
        "vst_plugin": DeviceCategory.VST_PLUGIN,
    }
    return mapping.get(category_str, DeviceCategory.OTHER)


async def ensure_manufacturer(
    db: AsyncSession, scraper: BaseScraper
) -> int:
    """Ensure manufacturer exists in database, create if not."""
    manufacturer = await device_service.get_manufacturer_by_slug(
        db, scraper.manufacturer_slug
    )
    if manufacturer:
        return manufacturer.id

    manufacturer = await device_service.create_manufacturer(
        db,
        ManufacturerCreate(
            name=scraper.manufacturer_name,
            slug=scraper.manufacturer_slug,
            website_url=scraper.manufacturer_website,
            scraper_type=scraper.scraper_type,
        ),
    )
    return manufacturer.id


async def sync_devices(
    db: AsyncSession, manufacturer_id: int, devices: List[ScrapedDevice]
) -> dict:
    """Sync scraped devices with database."""
    existing_models = await device_service.get_device_models(db, manufacturer_id)
    existing_by_name = {m.name: m for m in existing_models}

    created = 0
    updated = 0
    for device in devices:
        existing = existing_by_name.get(device.name)
        if existing is None:
            await device_service.create_device_model(
                db,
                DeviceModelCreate(
                    manufacturer_id=manufacturer_id,
                    name=device.name,
                    category=map_category(device.category),
                    firmware_page_url=device.firmware_page_url,
                    product_url=device.product_url,
                ),
            )
            created += 1
            continue

        # Refresh URLs that have moved. Without this a scraper can never correct a
        # dead link for a device already in the database -- the stale URL is used
        # forever and every fetch for that device fails.
        changes = {}
        if device.firmware_page_url and device.firmware_page_url != existing.firmware_page_url:
            changes["firmware_page_url"] = device.firmware_page_url
        if device.product_url and device.product_url != existing.product_url:
            changes["product_url"] = device.product_url
        if changes:
            await device_service.update_device_model(
                db, existing.id, DeviceModelUpdate(**changes)
            )
            updated += 1

    return {"created": created, "updated": updated, "total": len(devices)}


def parse_version(version: str) -> tuple:
    """Parse version string into comparable tuple."""
    import re
    # Extract numeric parts from version string
    parts = re.findall(r'\d+', version)
    return tuple(int(p) for p in parts) if parts else (0,)


async def sync_firmware_for_device(
    db: AsyncSession,
    device_model_id: int,
    firmware_versions: List[ScrapedFirmware],
) -> Tuple[int, Optional[str]]:
    """
    Sync firmware versions for a device model.
    Returns (new_count, latest_version_if_new).
    """
    existing = await device_service.get_firmware_versions(db, device_model_id)
    existing_versions = {fw.version for fw in existing}

    # Find current latest version
    current_latest = None
    for fw in existing:
        if fw.is_latest:
            current_latest = fw.version
            break

    new_versions = []

    # Add all new firmware versions (without marking as latest yet)
    for fw in firmware_versions:
        if fw.version not in existing_versions:
            await device_service.create_firmware_version(
                db,
                FirmwareVersionCreate(
                    device_model_id=device_model_id,
                    version=fw.version,
                    release_date=fw.release_date,
                    download_url=fw.download_url,
                    changelog_raw=fw.changelog,
                    is_latest=False,
                ),
            )
            new_versions.append(fw.version)

    # Determine the true latest version across all versions
    all_versions = list(existing_versions) + new_versions
    if all_versions:
        true_latest = max(all_versions, key=parse_version)

        # If the latest has changed, update the is_latest flag
        if true_latest != current_latest:
            # Clear old latest flag
            from sqlalchemy import update
            from src.devices.models import FirmwareVersion
            await db.execute(
                update(FirmwareVersion)
                .where(FirmwareVersion.device_model_id == device_model_id)
                .values(is_latest=False)
            )
            # Set new latest flag
            fw_record = await device_service.get_firmware_by_version(
                db, device_model_id, true_latest
            )
            if fw_record:
                fw_record.is_latest = True
                await db.commit()

            # Return the new latest only if it's actually new
            if true_latest in new_versions:
                return len(new_versions), true_latest

    return len(new_versions), None


async def create_update_notifications(
    db: AsyncSession,
    device_model_id: int,
    new_version: str,
) -> int:
    """Create notifications for all users tracking this device model."""
    # Get all user devices tracking this model
    all_devices = await device_service.get_my_devices(db)
    my_devices = [d for d in all_devices if d.device_model_id == device_model_id and d.notify_on_update]

    # Get the firmware version record
    firmware = await device_service.get_firmware_by_version(db, device_model_id, new_version)
    if not firmware:
        return 0

    notifications_created = 0
    for my_device in my_devices:
        # Same rule as the reconciliation pass, so the two paths cannot disagree.
        # A plain != notified devices whose installed version is unknown (None is not
        # equal to anything) and devices running a build newer than the vendor
        # publishes, neither of which is behind.
        if is_behind(my_device.current_firmware_version, new_version):
            device_model = await device_service.get_device_model(db, device_model_id)
            title = f"New firmware available: {device_model.name} v{new_version}"
            message = f"A new firmware version ({new_version}) is available for your {my_device.nickname or device_model.name}."

            await device_service.create_notification(
                db,
                NotificationCreate(
                    my_device_id=my_device.id,
                    firmware_version_id=firmware.id,
                    title=title,
                    message=message,
                ),
            )
            notifications_created += 1

            # Delivery is a side effect of the record, never a precondition for it:
            # the row is committed above and send() swallows its own failures.
            await get_notifier(get_settings()).send(
                title, message, url=firmware.download_url
            )

    return notifications_created


# A per-manufacturer budget must scale with device count, or it measures nothing: at
# a fixed 120s, Boss (16 devices at ~7s each) sat at 93% of budget while Native
# Instruments (40 devices, mostly cached lookups) used 13%. These allow roughly double
# the worst observed per-device cost, and stay under the 30s per-device ceiling.
SCRAPE_BUDGET_BASE = 30       # seconds, covers fetching the device list
SCRAPE_BUDGET_PER_DEVICE = 15  # seconds per device in the firmware loop

# Backstop for a scraper that is genuinely stuck rather than merely slow. The deadline
# inside the loop is what normally stops work; this only fires if that fails to.
SCRAPER_HARD_TIMEOUT = 900

# Kept for callers that still reference it.
SCRAPER_TIMEOUT = 120  # seconds per manufacturer (legacy fixed budget)


def scrape_budget_for(device_count: int) -> float:
    """Seconds allowed for one manufacturer, given how many devices it has."""
    return SCRAPE_BUDGET_BASE + SCRAPE_BUDGET_PER_DEVICE * max(device_count, 0)


async def scrape_manufacturer(
    db: AsyncSession, scraper_type: str
) -> dict:
    """
    Run a full scrape for a manufacturer.
    Returns summary of actions taken.
    """
    scraper = ScraperRegistry.create(scraper_type)
    if not scraper:
        return {"success": False, "error": f"Unknown scraper type: {scraper_type}"}

    try:
        # Ensure manufacturer exists
        manufacturer_id = await ensure_manufacturer(db, scraper)

        # Fetch and sync devices
        device_result = await scraper.fetch_device_list()
        if not device_result.success:
            return {"success": False, "error": device_result.error}

        device_sync = await sync_devices(db, manufacturer_id, device_result.devices)

        # Fetch firmware for each device
        device_models = await device_service.get_device_models(db, manufacturer_id)
        total_new_firmware = 0
        notifications_created = 0
        # Devices that yielded no firmware, split by cause. Scrapers generally report
        # success even when they find no versions, so without this the summary cannot
        # distinguish "scraped fine" from "scraped nothing at all". The two lists are
        # kept apart because they mean different things: a product can legitimately
        # have no firmware, which is not a failure to investigate.
        devices_without_firmware = []  # scraped OK, product has no firmware
        devices_failed = []  # fetch failed or timed out
        devices_not_checked = []  # budget ran out before reaching them

        # Stop the loop on a deadline rather than letting an outer timeout cancel the
        # whole scrape. A cancellation discards the summary even though each device's
        # data was already committed, so the database ends up right while the report
        # claims total failure.
        deadline = time.monotonic() + scrape_budget_for(len(device_models))

        for index, model in enumerate(device_models):
            if time.monotonic() > deadline:
                devices_not_checked = [m.name for m in device_models[index:]]
                print(
                    f"Budget exhausted for {scraper_type} after {index} of "
                    f"{len(device_models)} devices; {len(devices_not_checked)} not checked"
                )
                break

            if model.firmware_page_url:
                try:
                    fw_result = await asyncio.wait_for(
                        scraper.fetch_firmware_versions(
                            model.name, model.firmware_page_url
                        ),
                        timeout=30,
                    )
                except asyncio.TimeoutError:
                    print(f"Timeout fetching firmware for {model.name}, skipping")
                    devices_failed.append(model.name)
                    continue
                if fw_result.success and fw_result.firmware_versions:
                    new_count, latest = await sync_firmware_for_device(
                        db, model.id, fw_result.firmware_versions
                    )
                    total_new_firmware += new_count

                    # Create notifications for new versions
                    if latest:
                        notifs = await create_update_notifications(db, model.id, latest)
                        notifications_created += notifs
                elif fw_result.success:
                    devices_without_firmware.append(model.name)
                else:
                    devices_failed.append(model.name)

        # Update last_scraped_at timestamp on success
        await device_service.update_manufacturer(
            db, manufacturer_id, ManufacturerUpdate(last_scraped_at=datetime.utcnow())
        )

        return {
            "success": True,
            "manufacturer": scraper.manufacturer_name,
            "devices_synced": device_sync,
            "new_firmware_versions": total_new_firmware,
            "notifications_created": notifications_created,
            "devices_without_firmware": devices_without_firmware,
            "devices_failed": devices_failed,
            "devices_not_checked": devices_not_checked,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        await scraper.close()


async def scrape_all_manufacturers(db: AsyncSession) -> List[dict]:
    """Run scrape for all registered manufacturers."""
    results = []
    for scraper_type in ScraperRegistry.list_available():
        try:
            # scrape_manufacturer stops itself on its own budget and returns partial
            # results; this only catches a scraper stuck somewhere that never yields.
            result = await asyncio.wait_for(
                scrape_manufacturer(db, scraper_type),
                timeout=SCRAPER_HARD_TIMEOUT,
            )
        except asyncio.TimeoutError:
            result = {
                "success": False,
                "error": f"Hung past the {SCRAPER_HARD_TIMEOUT}s backstop",
                "manufacturer": scraper_type,
            }
        results.append(result)
    return results
