from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from src.database import get_db
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
