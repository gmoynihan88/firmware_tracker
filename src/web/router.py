from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from src.database import get_db
from src.config import get_settings
from src.devices import service as device_service
from src.devices.schemas import MyDeviceCreate, MyDeviceUpdate
from src.scrapers.registry import ScraperRegistry
from src.scrapers import service as scraper_service

settings = get_settings()
templates = Jinja2Templates(directory=str(settings.templates_dir))

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
        has_update = False
        if latest and device.current_firmware_version:
            has_update = latest.version != device.current_firmware_version
        elif latest:
            has_update = True

        devices_with_status.append({
            "device": device,
            "latest_firmware": latest,
            "has_update": has_update,
        })

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
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
        "add_device.html",
        {
            "request": request,
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
        "device_detail.html",
        {
            "request": request,
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
        "edit_device.html",
        {
            "request": request,
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
        "notifications.html",
        {
            "request": request,
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
    available_scrapers = ScraperRegistry.list_available()

    return templates.TemplateResponse(
        "catalog.html",
        {
            "request": request,
            "manufacturers": manufacturers,
            "device_models": device_models,
            "available_scrapers": available_scrapers,
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
        "partials/scrape_result.html",
        {"request": request, "result": result},
    )


@router.get("/partials/notification-badge", response_class=HTMLResponse)
async def notification_badge(request: Request, db: AsyncSession = Depends(get_db)):
    """HTMX polling endpoint for notification badge."""
    unread_count = await device_service.get_unread_count(db)
    return templates.TemplateResponse(
        "partials/notification_badge.html",
        {"request": request, "unread_count": unread_count},
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
        "partials/device_models_select.html",
        {"request": request, "device_models": device_models},
    )
