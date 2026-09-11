from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import logging

from src.config import get_settings
from src.database import async_session_maker
from src.notifications.reconcile import reconcile_notifications
from src.scrapers import service as scraper_service
from src.scrapers.cache import ResponseCache
from src.summarizer.service import summarize_pending_changelogs

scheduler = AsyncIOScheduler()

logger = logging.getLogger(__name__)

# A page nothing has fetched in this long is not coming back -- a discontinued
# product, or a URL the vendor moved.
RESPONSE_CACHE_MAX_AGE_DAYS = 14


async def check_firmware_updates():
    """Background job to check for firmware updates."""
    logger.info("Starting scheduled firmware check...")
    async with async_session_maker() as db:
        try:
            results = await scraper_service.scrape_all_manufacturers(db)
            total_new = sum(r.get("new_firmware_versions", 0) for r in results if r.get("success"))
            total_notifications = sum(r.get("notifications_created", 0) for r in results if r.get("success"))

            # Catch devices that are behind but whose latest version was already
            # known, so no scrape ever raised a notification for them.
            reconciled = await reconcile_notifications(db)
            total_notifications += reconciled["notifications_created"]

            total_failed = sum(len(r.get("devices_failed") or []) for r in results if r.get("success"))
            total_unchecked = sum(
                len(r.get("devices_not_checked") or []) for r in results if r.get("success")
            )
            logger.info(
                f"Firmware check complete. New versions: {total_new}, "
                f"Notifications: {total_notifications}, Devices failed: {total_failed}, "
                f"Not checked (budget): {total_unchecked}"
            )

            # Revalidation keeps every fetched body on disk, so the store needs a
            # bound. A 304 touches its entry, so anything still being scraped stays
            # young; what ages out is pages nothing asks for any more.
            _prune_response_cache()
        except Exception:
            # This runs unattended every 24 hours and nobody is watching when it
            # breaks, so the traceback is the whole diagnostic. str(e) alone is
            # often a bare message with no indication of where it came from.
            logger.exception("Error during firmware check")


def _prune_response_cache() -> None:
    """Drop cached responses nothing has asked for in a fortnight."""
    settings = get_settings()
    if not (settings.http_revalidate or settings.scrape_cache):
        return
    try:
        removed = ResponseCache(
            settings.scrape_cache_dir, settings.scrape_cache_ttl_hours * 3600
        ).prune(RESPONSE_CACHE_MAX_AGE_DAYS * 86400)
        if removed:
            logger.info(f"Pruned {removed} stale cached responses")
    except Exception as e:
        # Housekeeping must never take the scheduled check down with it.
        logger.warning(f"Could not prune the response cache: {e}")


async def generate_summaries():
    """Background job to generate AI summaries for changelogs."""
    logger.info("Starting changelog summarization...")
    async with async_session_maker() as db:
        try:
            count = await summarize_pending_changelogs(db)
            logger.info(f"Summarized {count} changelogs")
        except Exception:
            logger.exception("Error during summarization")


def start_scheduler():
    """Start the background scheduler.

    Settings are read here rather than at import, so the interval reflects what is
    configured when the app actually starts. A module-level read is captured the
    first time anything imports this, which is not necessarily the same thing.
    """
    settings = get_settings()

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
    """Shutdown the scheduler.

    AsyncIOScheduler dispatches its shutdown through the event loop, so this returns
    before the scheduler has actually stopped. That is fine here -- the lifespan is
    still running the loop -- but it means `scheduler.running` is briefly still true
    afterwards, which is surprising if you check.
    """
    scheduler.shutdown(wait=False)
    logger.info("Scheduler shutdown")
