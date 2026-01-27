from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import logging

from src.config import get_settings
from src.database import async_session_maker
from src.scrapers import service as scraper_service
from src.summarizer.service import summarize_pending_changelogs

settings = get_settings()
scheduler = AsyncIOScheduler()
logger = logging.getLogger(__name__)


async def check_firmware_updates():
    """Background job to check for firmware updates."""
    logger.info("Starting scheduled firmware check...")
    async with async_session_maker() as db:
        try:
            results = await scraper_service.scrape_all_manufacturers(db)
            total_new = sum(r.get("new_firmware_versions", 0) for r in results if r.get("success"))
            total_notifications = sum(r.get("notifications_created", 0) for r in results if r.get("success"))
            logger.info(
                f"Firmware check complete. New versions: {total_new}, Notifications: {total_notifications}"
            )
        except Exception as e:
            logger.error(f"Error during firmware check: {e}")


async def generate_summaries():
    """Background job to generate AI summaries for changelogs."""
    logger.info("Starting changelog summarization...")
    async with async_session_maker() as db:
        try:
            count = await summarize_pending_changelogs(db)
            logger.info(f"Summarized {count} changelogs")
        except Exception as e:
            logger.error(f"Error during summarization: {e}")


def start_scheduler():
    """Start the background scheduler."""
    # Check for firmware updates every N hours
    scheduler.add_job(
        check_firmware_updates,
        trigger=IntervalTrigger(hours=settings.scrape_interval_hours),
        id="firmware_check",
        name="Check for firmware updates",
        replace_existing=True,
    )

    # Generate summaries every hour (only processes pending ones)
    scheduler.add_job(
        generate_summaries,
        trigger=IntervalTrigger(hours=1),
        id="generate_summaries",
        name="Generate changelog summaries",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(f"Scheduler started. Firmware check interval: {settings.scrape_interval_hours} hours")


def shutdown_scheduler():
    """Shutdown the scheduler."""
    scheduler.shutdown(wait=False)
    logger.info("Scheduler shutdown")
