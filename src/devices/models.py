from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, DateTime, Float, Text, Enum
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


class FirmwareAvailability(str, enum.Enum):
    """Why a product has no version, when a scraper has established why.

    Only meaningful for a product with no firmware rows. A product that reports a
    version ignores this entirely, so nothing has to be cleared when a vendor starts
    publishing -- the version simply wins.

    The default is absence rather than a member: `NULL` means nobody has checked, and
    it is the honest state for most of these. Claiming a verified absence you have not
    verified is the mistake this whole project is arranged against, so a value is set
    only where a scraper's docstring can say how it was established.
    """

    # The vendor publishes no version anywhere public. Named for publication rather
    # than delivery: UA's UAFX pedals are installed by UA Connect and publish sixteen
    # dated versions, so "ships through the vendor's app" predicts nothing.
    NOT_PUBLISHED = "not_published"

    # The product takes no firmware updates at all -- TC Electronic's TonePrint pedals,
    # Peterson's analogue tuners. Different from the above: there is nothing to publish.
    NO_FIRMWARE = "no_firmware"


class Manufacturer(Base):
    __tablename__ = "manufacturers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True)
    slug = Column(String(255), nullable=False, unique=True)
    website_url = Column(String(500))
    scraper_type = Column(String(100))  # matches scraper plugin name
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_scraped_at = Column(DateTime, nullable=True)

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

    # Why this product reports no version, where a scraper has established why.
    # NULL means unexamined, which is most of them. See FirmwareAvailability.
    firmware_availability = Column(Enum(FirmwareAvailability), nullable=True)

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

    # First seen by this tracker. For roughly half the catalogue it is the only date
    # there is, because the vendor publishes none -- so it is never rewritten.
    created_at = Column(DateTime, default=datetime.utcnow)

    # Last confirmed still present on the vendor's page. A version the vendor has
    # withdrawn simply stops being returned, and without this its row looks identical
    # to one confirmed this morning. The gap between last_seen_at and now is also
    # what separates "still current" from "we stopped looking", which matters once
    # the database has been running long enough for that to be a real question.
    last_seen_at = Column(DateTime, default=datetime.utcnow, index=True)

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


class ScrapeRun(Base):
    """One record per manufacturer scrape, kept so gaps in the history are readable.

    Without this, a firmware version's first-seen date is the only evidence of time,
    and it cannot distinguish "the vendor published nothing for eight months" from
    "our scraper was quietly broken for eight months". Given how this project's
    scrapers fail -- reporting success while returning nothing, or the wrong thing --
    that is the difference between a trustworthy series and a misleading one.

    Counts rather than lists, except the failed device names, which are what you
    actually want when reading back why a month looks empty.
    """

    __tablename__ = "scrape_runs"

    id = Column(Integer, primary_key=True, index=True)
    scraper_type = Column(String(100), nullable=False, index=True)
    manufacturer_id = Column(Integer, ForeignKey("manufacturers.id"), nullable=True)

    started_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    finished_at = Column(DateTime)
    duration_seconds = Column(Float)

    # False covers both a scraper that raised and one that could not be created.
    success = Column(Boolean, nullable=False, default=False)
    error = Column(Text)

    devices_total = Column(Integer, default=0)
    devices_failed = Column(Integer, default=0)
    devices_without_firmware = Column(Integer, default=0)
    devices_not_checked = Column(Integer, default=0)
    new_versions = Column(Integer, default=0)
    notifications_created = Column(Integer, default=0)

    # Groups of different URLs that returned identical content. Non-zero means a URL
    # shape may have stopped selecting a product, which otherwise reads as the
    # vendor publishing nothing.
    identical_page_groups = Column(Integer, default=0)

    # JSON list of names, so a later reader can tell which products went quiet.
    failed_devices = Column(Text)

    manufacturer = relationship("Manufacturer")

    def __repr__(self):
        return f"<ScrapeRun({self.scraper_type} success={self.success})>"
