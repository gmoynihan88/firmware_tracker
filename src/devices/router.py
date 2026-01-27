from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from src.database import get_db
from src.devices import service
from src.devices.schemas import (
    ManufacturerCreate,
    ManufacturerUpdate,
    ManufacturerResponse,
    DeviceModelCreate,
    DeviceModelUpdate,
    DeviceModelResponse,
    DeviceModelWithManufacturer,
    FirmwareVersionResponse,
    MyDeviceCreate,
    MyDeviceUpdate,
    MyDeviceResponse,
    NotificationResponse,
)

router = APIRouter()


# Manufacturer endpoints
@router.get("/manufacturers", response_model=List[ManufacturerResponse])
async def list_manufacturers(db: AsyncSession = Depends(get_db)):
    return await service.get_manufacturers(db)


@router.get("/manufacturers/{manufacturer_id}", response_model=ManufacturerResponse)
async def get_manufacturer(manufacturer_id: int, db: AsyncSession = Depends(get_db)):
    manufacturer = await service.get_manufacturer(db, manufacturer_id)
    if not manufacturer:
        raise HTTPException(status_code=404, detail="Manufacturer not found")
    return manufacturer


@router.post("/manufacturers", response_model=ManufacturerResponse, status_code=201)
async def create_manufacturer(data: ManufacturerCreate, db: AsyncSession = Depends(get_db)):
    existing = await service.get_manufacturer_by_slug(db, data.slug)
    if existing:
        raise HTTPException(status_code=400, detail="Manufacturer with this slug already exists")
    return await service.create_manufacturer(db, data)


@router.patch("/manufacturers/{manufacturer_id}", response_model=ManufacturerResponse)
async def update_manufacturer(
    manufacturer_id: int, data: ManufacturerUpdate, db: AsyncSession = Depends(get_db)
):
    manufacturer = await service.update_manufacturer(db, manufacturer_id, data)
    if not manufacturer:
        raise HTTPException(status_code=404, detail="Manufacturer not found")
    return manufacturer


@router.delete("/manufacturers/{manufacturer_id}", status_code=204)
async def delete_manufacturer(manufacturer_id: int, db: AsyncSession = Depends(get_db)):
    deleted = await service.delete_manufacturer(db, manufacturer_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Manufacturer not found")


# DeviceModel endpoints
@router.get("/device-models", response_model=List[DeviceModelWithManufacturer])
async def list_device_models(
    manufacturer_id: int = None, db: AsyncSession = Depends(get_db)
):
    return await service.get_device_models(db, manufacturer_id)


@router.get("/device-models/{device_model_id}", response_model=DeviceModelWithManufacturer)
async def get_device_model(device_model_id: int, db: AsyncSession = Depends(get_db)):
    device_model = await service.get_device_model(db, device_model_id)
    if not device_model:
        raise HTTPException(status_code=404, detail="Device model not found")
    return device_model


@router.post("/device-models", response_model=DeviceModelResponse, status_code=201)
async def create_device_model(data: DeviceModelCreate, db: AsyncSession = Depends(get_db)):
    manufacturer = await service.get_manufacturer(db, data.manufacturer_id)
    if not manufacturer:
        raise HTTPException(status_code=404, detail="Manufacturer not found")
    return await service.create_device_model(db, data)


@router.patch("/device-models/{device_model_id}", response_model=DeviceModelResponse)
async def update_device_model(
    device_model_id: int, data: DeviceModelUpdate, db: AsyncSession = Depends(get_db)
):
    device_model = await service.update_device_model(db, device_model_id, data)
    if not device_model:
        raise HTTPException(status_code=404, detail="Device model not found")
    return device_model


@router.delete("/device-models/{device_model_id}", status_code=204)
async def delete_device_model(device_model_id: int, db: AsyncSession = Depends(get_db)):
    deleted = await service.delete_device_model(db, device_model_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Device model not found")


# FirmwareVersion endpoints
@router.get(
    "/device-models/{device_model_id}/firmware",
    response_model=List[FirmwareVersionResponse],
)
async def list_firmware_versions(device_model_id: int, db: AsyncSession = Depends(get_db)):
    device_model = await service.get_device_model(db, device_model_id)
    if not device_model:
        raise HTTPException(status_code=404, detail="Device model not found")
    return await service.get_firmware_versions(db, device_model_id)


# MyDevice endpoints
@router.get("/my-devices", response_model=List[MyDeviceResponse])
async def list_my_devices(db: AsyncSession = Depends(get_db)):
    return await service.get_my_devices(db)


@router.get("/my-devices/{my_device_id}", response_model=MyDeviceResponse)
async def get_my_device(my_device_id: int, db: AsyncSession = Depends(get_db)):
    my_device = await service.get_my_device(db, my_device_id)
    if not my_device:
        raise HTTPException(status_code=404, detail="Device not found")
    return my_device


@router.post("/my-devices", response_model=MyDeviceResponse, status_code=201)
async def create_my_device(data: MyDeviceCreate, db: AsyncSession = Depends(get_db)):
    device_model = await service.get_device_model(db, data.device_model_id)
    if not device_model:
        raise HTTPException(status_code=404, detail="Device model not found")
    return await service.create_my_device(db, data)


@router.patch("/my-devices/{my_device_id}", response_model=MyDeviceResponse)
async def update_my_device(
    my_device_id: int, data: MyDeviceUpdate, db: AsyncSession = Depends(get_db)
):
    my_device = await service.update_my_device(db, my_device_id, data)
    if not my_device:
        raise HTTPException(status_code=404, detail="Device not found")
    return my_device


@router.delete("/my-devices/{my_device_id}", status_code=204)
async def delete_my_device(my_device_id: int, db: AsyncSession = Depends(get_db)):
    deleted = await service.delete_my_device(db, my_device_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Device not found")


# Notification endpoints
@router.get("/notifications", response_model=List[NotificationResponse])
async def list_notifications(
    unread_only: bool = False, db: AsyncSession = Depends(get_db)
):
    return await service.get_notifications(db, unread_only)


@router.get("/notifications/count")
async def get_notification_count(db: AsyncSession = Depends(get_db)):
    count = await service.get_unread_count(db)
    return {"unread_count": count}


@router.post("/notifications/{notification_id}/read", status_code=204)
async def mark_notification_read(notification_id: int, db: AsyncSession = Depends(get_db)):
    success = await service.mark_notification_read(db, notification_id)
    if not success:
        raise HTTPException(status_code=404, detail="Notification not found")


@router.post("/notifications/read-all", status_code=204)
async def mark_all_read(db: AsyncSession = Depends(get_db)):
    await service.mark_all_notifications_read(db)
