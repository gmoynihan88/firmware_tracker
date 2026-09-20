from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
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
            total_fetches_failed = sum(
                len(r.get("fetches_failed") or []) for r in results if r.get("success")
            )
            logger.info(
                f"Firmware check complete. New versions: {total_new}, "
                f"Notifications: {total_notifications}, Devices failed: {total_failed}, "
                f"Not checked (budget): {total_unchecked}, Fetches failed: {total_fetches_failed}"
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


def _firmware_trigger(settings):
    """A wall-clock trigger for the firmware check, where the interval allows one.

    `scrape_interval_hours` stays the unit everything else reasons in -- /scrape-status
    derives its staleness threshold from it -- so this maps that interval onto the clock
    rather than replacing it. 24 hours becomes a single daily hour; a divisor of 24
    becomes a step anchored on `scrape_hour`, so 6 gives 03:00/09:00/15:00/21:00 and the
    configured hour is always one of them.

    An interval that is not a divisor of 24 cannot be said in hours-of-the-day without
    drift, so it keeps the old trigger and says so. Better a loud fallback than a
    schedule that silently means something other than what was asked for.

    The timezone is pinned to UTC rather than inherited from the host. APScheduler would
    otherwise use local time, which would make the hour mean one thing in the container
    and another on a laptop -- and the point of choosing 03:00 is to miss a backup window
    that is defined in UTC.
    """
    hours = settings.scrape_interval_hours
    anchor = settings.scrape_hour % 24

    if hours == 24:
        hour_field = str(anchor)
    elif 1 <= hours < 24 and 24 % hours == 0:
        hour_field = f"{anchor % hours}/{hours}"
    else:
        logger.warning(
            "scrape_interval_hours=%s is not a divisor of 24, so the check keeps an "
            "interval trigger and its clock restarts with the process.",
            hours,
        )
        return IntervalTrigger(hours=hours)

    return CronTrigger(hour=hour_field, minute=0, timezone="UTC")


def start_scheduler():
    """Start the background scheduler.

    Settings are read here rather than at import, so the interval reflects what is
    configured when the app actually starts. A module-level read is captured the
    first time anything imports this, which is not necessarily the same thing.
    """
    settings = get_settings()

    # Anchored to the clock, not to process start. An IntervalTrigger counts from when
    # the scheduler starts, and this scheduler runs in-process, so every deploy and every
    # Spot replacement pushed the next check a full interval into the future. Production
    # logged 12 "Scheduler started" lines across 2026-09-17/18 and exactly one firmware
    # check in that whole window -- a day of shipping scraped nothing, and nothing
    # anywhere reported that it had not.
    scheduler.add_job(
        check_firmware_updates,
        trigger=_firmware_trigger(settings),
        id="firmware_check",
        name="Check for firmware updates",
        replace_existing=True,
        # A sweep can outlast an interval; two at once would double every vendor's load
        # and put two writers on one SQLite file.
        max_instances=1,
        # If several fire times are missed, run once rather than catching up one by one.
        coalesce=True,
        # Covers the loop being busy at the fire time, which is the only misfire a memory
        # jobstore can see. It does NOT cover the process being down: a restart spanning
        # the scheduled minute still loses that occurrence. That is a ~6-minute window a
        # day rather than the whole day, and closing it properly means deriving the next
        # run from scrape_runs rather than from a trigger.
        misfire_grace_time=3600,
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
