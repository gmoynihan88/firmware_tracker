from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional
from src.devices.models import DeviceCategory, FirmwareAvailability


# Manufacturer schemas
class ManufacturerBase(BaseModel):
    name: str
    slug: str
    website_url: Optional[str] = None
    scraper_type: Optional[str] = None


class ManufacturerCreate(ManufacturerBase):
    pass


class ManufacturerUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    website_url: Optional[str] = None
    scraper_type: Optional[str] = None
    last_scraped_at: Optional[datetime] = None


class ManufacturerResponse(ManufacturerBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    last_scraped_at: Optional[datetime] = None


# DeviceModel schemas
class DeviceModelBase(BaseModel):
    name: str
    category: DeviceCategory = DeviceCategory.OTHER
    firmware_page_url: Optional[str] = None
    product_url: Optional[str] = None
    firmware_availability: Optional[FirmwareAvailability] = None


class DeviceModelCreate(DeviceModelBase):
    manufacturer_id: int


class DeviceModelUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[DeviceCategory] = None
    firmware_page_url: Optional[str] = None
    product_url: Optional[str] = None
    firmware_availability: Optional[FirmwareAvailability] = None


class DeviceModelResponse(DeviceModelBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    manufacturer_id: int
    created_at: datetime
    updated_at: datetime


class DeviceModelWithManufacturer(DeviceModelResponse):
    manufacturer: ManufacturerResponse


# FirmwareVersion schemas
class FirmwareVersionBase(BaseModel):
    version: str
    release_date: Optional[datetime] = None
    download_url: Optional[str] = None
    changelog_raw: Optional[str] = None
    changelog_summary: Optional[str] = None
    is_latest: bool = False


class FirmwareVersionCreate(FirmwareVersionBase):
    device_model_id: int


class FirmwareVersionResponse(FirmwareVersionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_model_id: int
    created_at: datetime


# MyDevice schemas
class MyDeviceBase(BaseModel):
    nickname: Optional[str] = None
    serial_number: Optional[str] = None
    current_firmware_version: Optional[str] = None
    notify_on_update: bool = True
    notes: Optional[str] = None


class MyDeviceCreate(MyDeviceBase):
    device_model_id: int


class MyDeviceUpdate(BaseModel):
    nickname: Optional[str] = None
    serial_number: Optional[str] = None
    current_firmware_version: Optional[str] = None
    notify_on_update: Optional[bool] = None
    notes: Optional[str] = None


class MyDeviceResponse(MyDeviceBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_model_id: int
    created_at: datetime
    updated_at: datetime


class MyDeviceWithDetails(MyDeviceResponse):
    device_model: DeviceModelWithManufacturer
    has_update: bool = False
    latest_firmware: Optional[FirmwareVersionResponse] = None


# Notification schemas
class NotificationBase(BaseModel):
    title: str
    message: Optional[str] = None


class NotificationCreate(NotificationBase):
    my_device_id: int
    firmware_version_id: int


class NotificationResponse(NotificationBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    my_device_id: int
    firmware_version_id: int
    read: bool
    created_at: datetime


class NotificationWithDetails(NotificationResponse):
    my_device: MyDeviceResponse
    firmware_version: FirmwareVersionResponse
