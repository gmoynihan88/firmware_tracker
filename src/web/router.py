from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from sqlalchemy import func, select

from src.database import get_db
from src.devices.models import DeviceModel, FirmwareVersion, Manufacturer, MyDevice, ScrapeRun
from src.config import get_settings
from src.devices import service as device_service
from src.devices.schemas import MyDeviceCreate, MyDeviceUpdate
from src.notifications.reconcile import is_behind
from src.scrapers.registry import ScraperRegistry
from src.scrapers import service as scraper_service

settings = get_settings()
# Shared environment, so asset_version() is available to every template.
from src.templating import templates  # noqa: E402

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    """Main dashboard showing all tracked devices and their firmware status."""
    my_devices = await device_service.get_my_devices(db)
    unread_count = await device_service.get_unread_count(db)

    # Enrich devices with firmware status
    devices_with_status = []
    for device in my_devices:
        latest = await device_service.get_latest_firmware(db, device.device_model_id)
        firmware_count = await device_service.get_firmware_version_count(db, device.device_model_id)

        # Three states, not two. A device with no recorded installed version is not
        # behind, it is unrecorded -- previously these were shown as "Update
        # Available", which is a guess, and the same numeric comparison the
        # notification paths use is applied here so the dashboard cannot disagree
        # with what gets notified.
        if not device.current_firmware_version:
            status = "unknown"
        elif latest and is_behind(device.current_firmware_version, latest.version):
            status = "update"
        else:
            status = "current"

        devices_with_status.append({
            "device": device,
            "latest_firmware": latest,
            "status": status,
            "has_update": status == "update",
            "firmware_count": firmware_count,
        })

    return templates.TemplateResponse(
        request,
        name="dashboard.html",
        context={
            "devices": devices_with_status,
            "unread_count": unread_count,
        },
    )


@router.get("/devices/add", response_class=HTMLResponse)
async def add_device_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Page to add a new device to track."""
    manufacturers = await device_service.get_manufacturers(db)
    device_models = await device_service.get_device_models(db)
    unread_count = await device_service.get_unread_count(db)

    return templates.TemplateResponse(
        request,
        name="add_device.html",
        context={
            "manufacturers": manufacturers,
            "device_models": device_models,
            "unread_count": unread_count,
        },
    )


@router.post("/devices/add")
async def add_device(
    request: Request,
    device_model_id: int = Form(...),
    nickname: Optional[str] = Form(None),
    current_firmware_version: Optional[str] = Form(None),
    notify_on_update: bool = Form(True),
    notes: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Handle adding a new device."""
    device_model = await device_service.get_device_model(db, device_model_id)
    if not device_model:
        raise HTTPException(status_code=404, detail="Device model not found")

    await device_service.create_my_device(
        db,
        MyDeviceCreate(
            device_model_id=device_model_id,
            nickname=nickname or None,
            current_firmware_version=current_firmware_version or None,
            notify_on_update=notify_on_update,
            notes=notes or None,
        ),
    )
    return RedirectResponse(url="/", status_code=303)


@router.get("/devices/{device_id}", response_class=HTMLResponse)
async def device_detail(
    request: Request, device_id: int, db: AsyncSession = Depends(get_db)
):
    """Device detail page with firmware history."""
    device = await device_service.get_my_device(db, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    firmware_versions = await device_service.get_firmware_versions(
        db, device.device_model_id
    )
    unread_count = await device_service.get_unread_count(db)

    return templates.TemplateResponse(
        request,
        name="device_detail.html",
        context={
            "device": device,
            "firmware_versions": firmware_versions,
            "unread_count": unread_count,
        },
    )


@router.get("/devices/{device_id}/edit", response_class=HTMLResponse)
async def edit_device_page(
    request: Request, device_id: int, db: AsyncSession = Depends(get_db)
):
    """Edit device page."""
    device = await device_service.get_my_device(db, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    firmware_versions = await device_service.get_firmware_versions(
        db, device.device_model_id
    )
    unread_count = await device_service.get_unread_count(db)

    return templates.TemplateResponse(
        request,
        name="edit_device.html",
        context={
            "device": device,
            "firmware_versions": firmware_versions,
            "unread_count": unread_count,
        },
    )


@router.post("/devices/{device_id}/edit")
async def edit_device(
    device_id: int,
    nickname: Optional[str] = Form(None),
    current_firmware_version: Optional[str] = Form(None),
    notify_on_update: bool = Form(False),
    notes: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Handle device update."""
    device = await device_service.update_my_device(
        db,
        device_id,
        MyDeviceUpdate(
            nickname=nickname or None,
            current_firmware_version=current_firmware_version or None,
            notify_on_update=notify_on_update,
            notes=notes or None,
        ),
    )
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return RedirectResponse(url=f"/devices/{device_id}", status_code=303)


@router.post("/devices/{device_id}/delete")
async def delete_device(device_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a device."""
    deleted = await device_service.delete_my_device(db, device_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Device not found")
    return RedirectResponse(url="/", status_code=303)


@router.get("/notifications", response_class=HTMLResponse)
async def notifications_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Notifications page."""
    notifications = await device_service.get_notifications(db)
    unread_count = await device_service.get_unread_count(db)

    return templates.TemplateResponse(
        request,
        name="notifications.html",
        context={
            "notifications": notifications,
            "unread_count": unread_count,
        },
    )


@router.post("/notifications/{notification_id}/read")
async def mark_read(notification_id: int, db: AsyncSession = Depends(get_db)):
    """Mark a notification as read (HTMX endpoint)."""
    await device_service.mark_notification_read(db, notification_id)
    return HTMLResponse(content="", status_code=200)


@router.post("/notifications/read-all")
async def mark_all_read(db: AsyncSession = Depends(get_db)):
    """Mark all notifications as read."""
    await device_service.mark_all_notifications_read(db)
    return RedirectResponse(url="/notifications", status_code=303)


@router.get("/catalog", response_class=HTMLResponse)
async def catalog_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Device catalog browsing page."""
    manufacturers = await device_service.get_manufacturers(db)
    device_models = await device_service.get_device_models(db)
    unread_count = await device_service.get_unread_count(db)

    # The registry lists slugs, and the template used to title-case them, which
    # rendered "Ikmultimedia", "Izotope", "Line6" and "Nativeinstruments". Each
    # scraper carries the vendor's own spelling, so use that.
    device_counts = {
        row[0]: row[1]
        for row in (
            await db.execute(
                select(Manufacturer.slug, func.count(DeviceModel.id))
                .join(DeviceModel, DeviceModel.manufacturer_id == Manufacturer.id)
                .group_by(Manufacturer.slug)
            )
        ).all()
    }

    # Most recent successful run per scraper, so a vendor card can say when it last
    # worked rather than only offering to run again. scrape_runs only goes back to
    # the day that table was added, so manufacturers.last_scraped_at -- maintained
    # since the beginning -- is the fallback. Without it every vendor scraped before
    # then reads "never scraped", which is worse than the gap it describes.
    last_runs = {
        row[0]: row[1]
        for row in (
            await db.execute(
                select(ScrapeRun.scraper_type, func.max(ScrapeRun.started_at))
                .where(ScrapeRun.success.is_(True))
                .group_by(ScrapeRun.scraper_type)
            )
        ).all()
    }

    vendor_rows = (
        await db.execute(
            select(Manufacturer.slug, Manufacturer.website_url, Manufacturer.last_scraped_at)
        )
    ).all()
    websites = {row[0]: row[1] for row in vendor_rows}
    legacy_scraped = {row[0]: row[2] for row in vendor_rows}

    available_scrapers = [
        {
            "slug": slug,
            "name": ScraperRegistry.get(slug).manufacturer_name,
            "device_count": device_counts.get(slug, 0),
            "last_run": last_runs.get(slug) or legacy_scraped.get(slug),
            "website": websites.get(slug) or ScraperRegistry.get(slug).manufacturer_website,
        }
        for slug in sorted(
            ScraperRegistry.list_available(),
            key=lambda s: ScraperRegistry.get(s).manufacturer_name.lower(),
        )
    ]

    # Which models the user already tracks, so the table can say so instead of
    # offering to add a second copy of something they have.
    tracked_model_ids = {
        row[0] for row in (await db.execute(select(MyDevice.device_model_id))).all()
    }

    # Latest known version per model, in one query rather than one per row.
    latest_versions = {
        row[0]: row[1]
        for row in (
            await db.execute(
                select(FirmwareVersion.device_model_id, FirmwareVersion.version)
                .where(FirmwareVersion.is_latest.is_(True))
            )
        ).all()
    }

    return templates.TemplateResponse(
        request,
        name="catalog.html",
        context={
            "manufacturers": manufacturers,
            "device_models": device_models,
            "available_scrapers": available_scrapers,
            "tracked_model_ids": tracked_model_ids,
            "latest_versions": latest_versions,
            "unread_count": unread_count,
        },
    )


@router.post("/catalog/scrape/{scraper_type}")
async def scrape_manufacturer(
    request: Request,
    scraper_type: str,
    db: AsyncSession = Depends(get_db),
):
    """Trigger a scrape for a manufacturer (HTMX endpoint)."""
    result = await scraper_service.scrape_manufacturer(db, scraper_type)
    return templates.TemplateResponse(
        request,
        name="partials/scrape_result.html",
        context={"result": result},
    )


@router.get("/partials/notification-badge", response_class=HTMLResponse)
async def notification_badge(request: Request, db: AsyncSession = Depends(get_db)):
    """HTMX polling endpoint for notification badge."""
    unread_count = await device_service.get_unread_count(db)
    return templates.TemplateResponse(
        request,
        name="partials/notification_badge.html",
        context={"unread_count": unread_count},
    )


@router.get("/partials/device-models", response_class=HTMLResponse)
async def device_models_partial(
    request: Request,
    manufacturer_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    """HTMX endpoint to load device models for a manufacturer."""
    device_models = []
    if manufacturer_id:
        device_models = await device_service.get_device_models(db, manufacturer_id)
    return templates.TemplateResponse(
        request,
        name="partials/device_models_select.html",
        context={"device_models": device_models},
    )
