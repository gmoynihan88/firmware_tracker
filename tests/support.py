"""Shared test harness: the in-memory database and helpers used by more than one test module."""

import os
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.database import enforce_foreign_keys

# Use an in-memory SQLite database for tests so the production DB is never touched
test_engine = create_async_engine("sqlite+aiosqlite://", echo=False)
# The app enforces foreign keys; an engine that does not is not testing the app.
enforce_foreign_keys(test_engine.sync_engine)
test_session_maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def override_get_db():
    async with test_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


def chromium_is_installed() -> bool:
    """Whether Playwright's Chromium is on disk -- answered without starting anything.

    Asking Playwright directly means `async_playwright().start()`, which spawns its
    driver as an asyncio subprocess. On Python 3.12 a driver started only to discover
    the browser is missing leaves a transport that is finalised after the test's event
    loop has closed, and `BaseSubprocessTransport.__del__` then calls into the dead
    loop: `RuntimeError: Event loop is closed`, surfaced by pytest's unraisable hook.
    CI installs the Playwright package but not the browsers, so both browser tests hit
    that on every run -- two errors an otherwise green build had to carry.

    Reading the download directory answers the same question with no subprocess at all.

    This is allowed to be wrong only in the optimistic direction: the callers keep
    their launch-failure skip, so a true answer that turns out false still skips
    cleanly. A false answer where the browser exists would silently drop real
    coverage, which is why PLAYWRIGHT_BROWSERS_PATH=0 -- browsers stored beside the
    package, where this cannot see them -- returns True and lets the launch decide.
    """
    root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if root == "0":
        return True
    if not root:
        home = Path.home()
        root = {
            "darwin": home / "Library" / "Caches" / "ms-playwright",
            "win32": home / "AppData" / "Local" / "ms-playwright",
        }.get(sys.platform, home / ".cache" / "ms-playwright")
    return any(Path(root).glob("chromium-*"))


async def _seed_notification(version: str = "2.0.0", slug: str = "notifyco"):
    """Create a tracked device with a newer firmware version and a notification.

    The slug is a parameter because manufacturers.slug is unique, and seeding twice
    in one test is the normal case for anything counting notifications.
    """
    from src.devices import service as ds
    from src.devices.models import DeviceCategory, Notification
    from src.devices.schemas import (
        DeviceModelCreate, FirmwareVersionCreate, ManufacturerCreate, MyDeviceCreate,
    )

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(db, ManufacturerCreate(name=f"Notify {slug}", slug=slug))
        model = await ds.create_device_model(db, DeviceModelCreate(
            manufacturer_id=mfr.id, name=f"Notify Box {slug}", category=DeviceCategory.OTHER,
        ))
        firmware = await ds.create_firmware_version(db, FirmwareVersionCreate(
            device_model_id=model.id, version=version, is_latest=True,
        ))
        mine = await ds.create_my_device(db, MyDeviceCreate(
            device_model_id=model.id, current_firmware_version="1.0.0",
        ))
        note = Notification(
            my_device_id=mine.id,
            firmware_version_id=firmware.id,
            title=f"Notify Box {slug} {version} available",
            message=f"Update from 1.0.0 to {version}",
            read=False,
        )
        db.add(note)
        await db.commit()
        await db.refresh(note)
        return note.id


async def _seed_unversioned(name, slug, availability=None):
    from src.devices import service as ds
    from src.devices.models import DeviceCategory
    from src.devices.schemas import DeviceModelCreate, ManufacturerCreate

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(db, ManufacturerCreate(name=name, slug=slug))
        return await ds.create_device_model(db, DeviceModelCreate(
            manufacturer_id=mfr.id, name=f"{name} Box",
            category=DeviceCategory.AUDIO_INTERFACE,
            firmware_availability=availability,
        ))


def _stub_fetch(scraper, pages, attr="fetch_page"):
    """Serve canned pages and record what was asked for."""
    asked = []

    async def fake(url, **kwargs):
        asked.append(url)
        return pages.get(url)

    setattr(scraper, attr, fake)
    return asked
