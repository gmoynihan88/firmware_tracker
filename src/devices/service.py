import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from sqlalchemy.orm import selectinload
from typing import Optional, Sequence

from src.devices.models import (
    Manufacturer,
    DeviceModel,
    FirmwareVersion,
    MyDevice,
    Notification,
)
from src.devices.schemas import (
    ManufacturerCreate,
    ManufacturerUpdate,
    DeviceModelCreate,
    DeviceModelUpdate,
    MyDeviceCreate,
    MyDeviceUpdate,
    FirmwareVersionCreate,
    NotificationCreate,
)


# Manufacturer CRUD
async def get_manufacturers(db: AsyncSession) -> Sequence[Manufacturer]:
    result = await db.execute(select(Manufacturer).order_by(Manufacturer.name))
    return result.scalars().all()


async def get_manufacturer(db: AsyncSession, manufacturer_id: int) -> Optional[Manufacturer]:
    result = await db.execute(select(Manufacturer).where(Manufacturer.id == manufacturer_id))
    return result.scalar_one_or_none()


async def get_manufacturer_by_slug(db: AsyncSession, slug: str) -> Optional[Manufacturer]:
    result = await db.execute(select(Manufacturer).where(Manufacturer.slug == slug))
    return result.scalar_one_or_none()


async def create_manufacturer(db: AsyncSession, data: ManufacturerCreate) -> Manufacturer:
    manufacturer = Manufacturer(**data.model_dump())
    db.add(manufacturer)
    await db.commit()
    await db.refresh(manufacturer)
    return manufacturer


async def update_manufacturer(
    db: AsyncSession, manufacturer_id: int, data: ManufacturerUpdate
) -> Optional[Manufacturer]:
    manufacturer = await get_manufacturer(db, manufacturer_id)
    if not manufacturer:
        return None
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(manufacturer, key, value)
    await db.commit()
    await db.refresh(manufacturer)
    return manufacturer


# Deletes go through the ORM rather than a bulk `delete()` statement.
#
# Every relationship in models.py already declares `cascade="all, delete-orphan"`,
# but a Core `delete(X).where(...)` never consults the ORM, so none of it ran.
# Deleting one device model left its firmware versions behind pointing at an id
# that no longer existed -- rows nothing can reach and nothing counts, which is
# how two of them sat in the development database until a catalog column made
# the arithmetic visible. SQLite does not enforce foreign keys by default either,
# so there was nothing underneath to catch it.
#
# `session.delete()` on a loaded object walks the declared cascades:
#   manufacturer -> device models -> firmware versions -> notifications
#                                 -> my devices        -> notifications
# It costs a SELECT per delete, on an operation that happens by hand.


async def delete_manufacturer(db: AsyncSession, manufacturer_id: int) -> bool:
    manufacturer = await db.get(Manufacturer, manufacturer_id)
    if manufacturer is None:
        return False
    await db.delete(manufacturer)
    await db.commit()
    return True


# DeviceModel CRUD
async def get_device_models(
    db: AsyncSession, manufacturer_id: Optional[int] = None
) -> Sequence[DeviceModel]:
    query = select(DeviceModel).options(selectinload(DeviceModel.manufacturer))
    if manufacturer_id:
        query = query.where(DeviceModel.manufacturer_id == manufacturer_id)
    query = query.order_by(DeviceModel.name)
    result = await db.execute(query)
    return result.scalars().all()


async def get_device_model(db: AsyncSession, device_model_id: int) -> Optional[DeviceModel]:
    result = await db.execute(
        select(DeviceModel)
        .options(selectinload(DeviceModel.manufacturer))
        .where(DeviceModel.id == device_model_id)
    )
    return result.scalar_one_or_none()


async def create_device_model(db: AsyncSession, data: DeviceModelCreate) -> DeviceModel:
    device_model = DeviceModel(**data.model_dump())
    db.add(device_model)
    await db.commit()
    await db.refresh(device_model)
    return device_model


async def update_device_model(
    db: AsyncSession, device_model_id: int, data: DeviceModelUpdate
) -> Optional[DeviceModel]:
    device_model = await get_device_model(db, device_model_id)
    if not device_model:
        return None
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(device_model, key, value)
    await db.commit()
    await db.refresh(device_model)
    return device_model


async def delete_device_model(db: AsyncSession, device_model_id: int) -> bool:
    device_model = await db.get(DeviceModel, device_model_id)
    if device_model is None:
        return False
    await db.delete(device_model)
    await db.commit()
    return True


# FirmwareVersion CRUD
def _parse_version(version: str) -> tuple:
    """Parse version string into comparable tuple for sorting."""
    parts = re.findall(r'\d+', version)
    return tuple(int(p) for p in parts) if parts else (0,)


async def get_firmware_versions(
    db: AsyncSession, device_model_id: int
) -> Sequence[FirmwareVersion]:
    result = await db.execute(
        select(FirmwareVersion)
        .where(FirmwareVersion.device_model_id == device_model_id)
    )
    versions = result.scalars().all()
    # Sort by version number descending (highest first)
    return sorted(versions, key=lambda fw: _parse_version(fw.version), reverse=True)


async def get_latest_firmware(
    db: AsyncSession, device_model_id: int
) -> Optional[FirmwareVersion]:
    result = await db.execute(
        select(FirmwareVersion)
        .where(FirmwareVersion.device_model_id == device_model_id)
        .where(FirmwareVersion.is_latest == True)
    )
    return result.scalar_one_or_none()


async def get_firmware_version_count(db: AsyncSession, device_model_id: int) -> int:
    result = await db.execute(
        select(func.count(FirmwareVersion.id))
        .where(FirmwareVersion.device_model_id == device_model_id)
    )
    return result.scalar() or 0


async def get_firmware_by_version(
    db: AsyncSession, device_model_id: int, version: str
) -> Optional[FirmwareVersion]:
    result = await db.execute(
        select(FirmwareVersion)
        .where(FirmwareVersion.device_model_id == device_model_id)
        .where(FirmwareVersion.version == version)
    )
    return result.scalar_one_or_none()


async def create_firmware_version(
    db: AsyncSession, data: FirmwareVersionCreate
) -> FirmwareVersion:
    # If this is marked as latest, unset any existing latest
    if data.is_latest:
        await db.execute(
            update(FirmwareVersion)
            .where(FirmwareVersion.device_model_id == data.device_model_id)
            .values(is_latest=False)
        )
    firmware = FirmwareVersion(**data.model_dump())
    db.add(firmware)
    await db.commit()
    await db.refresh(firmware)
    return firmware


async def update_firmware_summary(
    db: AsyncSession, firmware_id: int, summary: str
) -> Optional[FirmwareVersion]:
    result = await db.execute(
        select(FirmwareVersion).where(FirmwareVersion.id == firmware_id)
    )
    firmware = result.scalar_one_or_none()
    if firmware:
        firmware.changelog_summary = summary
        await db.commit()
        await db.refresh(firmware)
    return firmware


# MyDevice CRUD
async def get_my_devices(db: AsyncSession) -> Sequence[MyDevice]:
    result = await db.execute(
        select(MyDevice)
        .options(
            selectinload(MyDevice.device_model).selectinload(DeviceModel.manufacturer)
        )
        .order_by(MyDevice.created_at.desc())
    )
    return result.scalars().all()


async def get_my_device(db: AsyncSession, my_device_id: int) -> Optional[MyDevice]:
    result = await db.execute(
        select(MyDevice)
        .options(
            selectinload(MyDevice.device_model).selectinload(DeviceModel.manufacturer)
        )
        .where(MyDevice.id == my_device_id)
    )
    return result.scalar_one_or_none()


async def create_my_device(db: AsyncSession, data: MyDeviceCreate) -> MyDevice:
    my_device = MyDevice(**data.model_dump())
    db.add(my_device)
    await db.commit()
    await db.refresh(my_device)
    return my_device


async def update_my_device(
    db: AsyncSession, my_device_id: int, data: MyDeviceUpdate
) -> Optional[MyDevice]:
    my_device = await get_my_device(db, my_device_id)
    if not my_device:
        return None
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(my_device, key, value)
    await db.commit()
    await db.refresh(my_device)
    return my_device


async def delete_my_device(db: AsyncSession, my_device_id: int) -> bool:
    my_device = await db.get(MyDevice, my_device_id)
    if my_device is None:
        return False
    await db.delete(my_device)
    await db.commit()
    return True


# Notification CRUD
async def get_notifications(
    db: AsyncSession, unread_only: bool = False
) -> Sequence[Notification]:
    query = select(Notification).options(
        selectinload(Notification.my_device),
        selectinload(Notification.firmware_version),
    )
    if unread_only:
        query = query.where(Notification.read == False)
    query = query.order_by(Notification.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


async def get_unread_count(db: AsyncSession) -> int:
    result = await db.execute(
        select(Notification).where(Notification.read == False)
    )
    return len(result.scalars().all())


async def create_notification(db: AsyncSession, data: NotificationCreate) -> Notification:
    notification = Notification(**data.model_dump())
    db.add(notification)
    await db.commit()
    await db.refresh(notification)
    return notification


async def mark_notification_read(db: AsyncSession, notification_id: int) -> bool:
    result = await db.execute(
        update(Notification)
        .where(Notification.id == notification_id)
        .values(read=True)
    )
    await db.commit()
    return result.rowcount > 0


async def mark_all_notifications_read(db: AsyncSession) -> int:
    result = await db.execute(
        update(Notification).where(Notification.read == False).values(read=True)
    )
    await db.commit()
    return result.rowcount
