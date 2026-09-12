import json

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from src.database import get_db
from src.devices.models import ScrapeRun
from src.scrapers.registry import ScraperRegistry
from src.scrapers import service as scraper_service
from src.notifications.reconcile import reconcile_notifications

router = APIRouter()


@router.get("/scrapers")
async def list_scrapers():
    """List all available scrapers."""
    return {
        "scrapers": ScraperRegistry.list_available(),
        "manufacturers": ScraperRegistry.get_manufacturer_info(),
    }


@router.post("/scrape/{scraper_type}")
async def scrape_manufacturer(
    scraper_type: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Trigger a manual scrape for a specific manufacturer."""
    if scraper_type not in ScraperRegistry.list_available():
        raise HTTPException(status_code=404, detail=f"Scraper '{scraper_type}' not found")

    result = await scraper_service.scrape_manufacturer(db, scraper_type)
    return result


@router.post("/scrape-all")
async def scrape_all(db: AsyncSession = Depends(get_db)):
    """Trigger a manual scrape for all manufacturers."""
    results = await scraper_service.scrape_all_manufacturers(db)
    return {"results": results}


@router.post("/reconcile-notifications")
async def reconcile(db: AsyncSession = Depends(get_db)):
    """Raise notifications for tracked devices behind their latest known firmware.

    Scraping only notifies about versions it discovers, so a device whose installed
    version was recorded after its latest was already known never gets one. This
    fills those in. Idempotent: one notification per device per version.
    """
    return await reconcile_notifications(db)


@router.get("/runs")
async def list_scrape_runs(
    scraper_type: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """Recent scrape runs, newest first.

    The table is only useful if it can be read back. The question it answers is
    whether a quiet stretch in a device's history means the vendor published nothing
    or the scraper stopped working, and that needs the runs beside the versions.
    """
    query = select(ScrapeRun).order_by(ScrapeRun.started_at.desc()).limit(min(limit, 500))
    if scraper_type:
        query = query.where(ScrapeRun.scraper_type == scraper_type)

    runs = (await db.execute(query)).scalars().all()
    return [
        {
            "scraper_type": run.scraper_type,
            "started_at": run.started_at,
            "duration_seconds": run.duration_seconds,
            "success": run.success,
            "error": run.error,
            "devices_total": run.devices_total,
            "devices_failed": run.devices_failed,
            "devices_without_firmware": run.devices_without_firmware,
            "devices_not_checked": run.devices_not_checked,
            "new_versions": run.new_versions,
            "identical_page_groups": run.identical_page_groups,
            "failed_devices": json.loads(run.failed_devices) if run.failed_devices else [],
        }
        for run in runs
    ]
