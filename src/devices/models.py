from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, DateTime, Text, Enum
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

from src.database import Base


class DeviceCategory(str, enum.Enum):
    GUITAR_PEDAL = "guitar_pedal"
    AUDIO_INTERFACE = "audio_interface"
    SYNTHESIZER = "synthesizer"
    MIDI_CONTROLLER = "midi_controller"
    VST_PLUGIN = "vst_plugin"
    OTHER = "other"


class Manufacturer(Base):
    __tablename__ = "manufacturers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True)
    slug = Column(String(255), nullable=False, unique=True)
    website_url = Column(String(500))
    scraper_type = Column(String(100))  # matches scraper plugin name
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    device_models = relationship("DeviceModel", back_populates="manufacturer", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Manufacturer(name={self.name})>"


class DeviceModel(Base):
    __tablename__ = "device_models"

    id = Column(Integer, primary_key=True, index=True)
    manufacturer_id = Column(Integer, ForeignKey("manufacturers.id"), nullable=False)
    name = Column(String(255), nullable=False)
    category = Column(Enum(DeviceCategory), default=DeviceCategory.OTHER)
    firmware_page_url = Column(String(500))
    product_url = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    manufacturer = relationship("Manufacturer", back_populates="device_models")
    firmware_versions = relationship("FirmwareVersion", back_populates="device_model", cascade="all, delete-orphan")
    my_devices = relationship("MyDevice", back_populates="device_model", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<DeviceModel(name={self.name})>"


class FirmwareVersion(Base):
    __tablename__ = "firmware_versions"

    id = Column(Integer, primary_key=True, index=True)
    device_model_id = Column(Integer, ForeignKey("device_models.id"), nullable=False)
    version = Column(String(50), nullable=False)
    release_date = Column(DateTime)
    download_url = Column(String(500))
    changelog_raw = Column(Text)
    changelog_summary = Column(Text)
    is_latest = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    device_model = relationship("DeviceModel", back_populates="firmware_versions")
    notifications = relationship("Notification", back_populates="firmware_version", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<FirmwareVersion(version={self.version})>"


class MyDevice(Base):
    __tablename__ = "my_devices"

    id = Column(Integer, primary_key=True, index=True)
    device_model_id = Column(Integer, ForeignKey("device_models.id"), nullable=False)
    nickname = Column(String(255))
    serial_number = Column(String(255))
    current_firmware_version = Column(String(50))
    notify_on_update = Column(Boolean, default=True)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    device_model = relationship("DeviceModel", back_populates="my_devices")
    notifications = relationship("Notification", back_populates="my_device", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<MyDevice(nickname={self.nickname})>"


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    my_device_id = Column(Integer, ForeignKey("my_devices.id"), nullable=False)
    firmware_version_id = Column(Integer, ForeignKey("firmware_versions.id"), nullable=False)
    title = Column(String(255), nullable=False)
    message = Column(Text)
    read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    my_device = relationship("MyDevice", back_populates="notifications")
    firmware_version = relationship("FirmwareVersion", back_populates="notifications")

    def __repr__(self):
        return f"<Notification(title={self.title})>"
