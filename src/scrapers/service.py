from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Tuple
from datetime import datetime

from src.scrapers.registry import ScraperRegistry
from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult
from src.devices import service as device_service
from src.devices.schemas import (
    ManufacturerCreate,
    DeviceModelCreate,
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
    existing_names = {m.name for m in existing_models}

    created = 0
    for device in devices:
        if device.name not in existing_names:
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

    return {"created": created, "total": len(devices)}


async def sync_firmware_for_device(
    db: AsyncSession,
    device_model_id: int,
    firmware_versions: List[ScrapedFirmware],
) -> Tuple[int, Optional[str]]:
    """
    Sync firmware versions for a device model.
    Returns (new_count, latest_version).
    """
    existing = await device_service.get_firmware_versions(db, device_model_id)
    existing_versions = {fw.version for fw in existing}

    new_versions = []
    latest_version = None

    for i, fw in enumerate(firmware_versions):
        if fw.version not in existing_versions:
            is_latest = i == 0  # First in list is typically latest
            await device_service.create_firmware_version(
                db,
                FirmwareVersionCreate(
                    device_model_id=device_model_id,
                    version=fw.version,
                    release_date=fw.release_date,
                    download_url=fw.download_url,
                    changelog_raw=fw.changelog,
                    is_latest=is_latest,
                ),
            )
            new_versions.append(fw.version)
            if is_latest:
                latest_version = fw.version

    return len(new_versions), latest_version


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
        # Check if user is not already on this version
        if my_device.current_firmware_version != new_version:
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

    return notifications_created


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

        for model in device_models:
            if model.firmware_page_url:
                fw_result = await scraper.fetch_firmware_versions(
                    model.name, model.firmware_page_url
                )
                if fw_result.success and fw_result.firmware_versions:
                    new_count, latest = await sync_firmware_for_device(
                        db, model.id, fw_result.firmware_versions
                    )
                    total_new_firmware += new_count

                    # Create notifications for new versions
                    if latest:
                        notifs = await create_update_notifications(db, model.id, latest)
                        notifications_created += notifs

        return {
            "success": True,
            "manufacturer": scraper.manufacturer_name,
            "devices_synced": device_sync,
            "new_firmware_versions": total_new_firmware,
            "notifications_created": notifications_created,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        await scraper.close()


async def scrape_all_manufacturers(db: AsyncSession) -> List[dict]:
    """Run scrape for all registered manufacturers."""
    results = []
    for scraper_type in ScraperRegistry.list_available():
        result = await scrape_manufacturer(db, scraper_type)
        results.append(result)
    return results
