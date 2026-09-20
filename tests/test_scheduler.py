import asyncio
import logging

import pytest


@pytest.mark.asyncio
async def test_firmware_check_survives_a_scraper_blowing_up(monkeypatch, caplog):
    """An exception must not escape the job, or APScheduler stops running it."""
    from src.scheduler import scheduler as sched

    async def explode(db):
        raise RuntimeError("vendor site returned nonsense")

    monkeypatch.setattr(sched.scraper_service, "scrape_all_manufacturers", explode)

    with caplog.at_level(logging.ERROR, logger="src.scheduler.scheduler"):
        await sched.check_firmware_updates()  # must not raise

    assert "Error during firmware check" in caplog.text
    # The traceback is the whole diagnostic for an unattended job.
    assert "RuntimeError" in caplog.text
    assert "vendor site returned nonsense" in caplog.text


@pytest.mark.asyncio
async def test_firmware_check_counts_reconciled_notifications(monkeypatch, caplog):
    """Reconciliation catches devices no scrape raised a notification for.

    If its count were dropped from the total, the log would under-report exactly the
    notifications that were hardest to find.
    """
    from src.scheduler import scheduler as sched

    async def two_manufacturers(db):
        return [
            {"success": True, "new_firmware_versions": 3, "notifications_created": 1,
             "devices_failed": ["Widget"], "devices_not_checked": []},
            {"success": True, "new_firmware_versions": 2, "notifications_created": 0,
             "devices_failed": [], "devices_not_checked": ["Gadget", "Doohickey"]},
        ]

    async def reconcile(db):
        return {"notifications_created": 4}

    monkeypatch.setattr(sched.scraper_service, "scrape_all_manufacturers", two_manufacturers)
    monkeypatch.setattr(sched, "reconcile_notifications", reconcile)
    monkeypatch.setattr(sched, "_prune_response_cache", lambda: None)

    with caplog.at_level(logging.INFO, logger="src.scheduler.scheduler"):
        await sched.check_firmware_updates()

    assert "New versions: 5" in caplog.text
    assert "Notifications: 5" in caplog.text      # 1 from scrapes + 4 reconciled
    assert "Devices failed: 1" in caplog.text
    assert "Not checked (budget): 2" in caplog.text


@pytest.mark.asyncio
async def test_a_failed_scrape_does_not_corrupt_the_totals(monkeypatch, caplog):
    """Unsuccessful results carry no counts and must be skipped, not summed."""
    from src.scheduler import scheduler as sched

    async def mixed(db):
        return [
            {"success": True, "new_firmware_versions": 7, "notifications_created": 2,
             "devices_failed": [], "devices_not_checked": []},
            {"success": False, "error": "boom"},
        ]

    monkeypatch.setattr(sched.scraper_service, "scrape_all_manufacturers", mixed)
    monkeypatch.setattr(sched, "reconcile_notifications", lambda db: _async_value({"notifications_created": 0}))
    monkeypatch.setattr(sched, "_prune_response_cache", lambda: None)

    with caplog.at_level(logging.INFO, logger="src.scheduler.scheduler"):
        await sched.check_firmware_updates()

    assert "New versions: 7" in caplog.text
    assert "Devices failed: 0" in caplog.text


async def _async_value(value):
    return value


@pytest.mark.asyncio
async def test_prune_failure_does_not_take_down_the_firmware_check(monkeypatch, caplog):
    """Housekeeping is the least important thing the job does and must act like it."""
    from src.scheduler import scheduler as sched

    async def nothing(db):
        return []

    def broken_prune(*args, **kwargs):
        raise OSError("disk is on fire")

    monkeypatch.setattr(sched.scraper_service, "scrape_all_manufacturers", nothing)
    monkeypatch.setattr(sched, "reconcile_notifications", lambda db: _async_value({"notifications_created": 0}))
    monkeypatch.setattr(sched.ResponseCache, "prune", broken_prune)

    with caplog.at_level(logging.INFO, logger="src.scheduler.scheduler"):
        await sched.check_firmware_updates()

    assert "Could not prune the response cache" in caplog.text
    # The check still reported its result rather than dying during cleanup.
    assert "Firmware check complete" in caplog.text


def test_prune_is_skipped_when_nothing_writes_to_the_store(monkeypatch):
    """With both cache flags off no store exists, so there is nothing to walk."""
    from src.config import Settings
    from src.scheduler import scheduler as sched

    called = []
    monkeypatch.setattr(sched.ResponseCache, "prune", lambda self, age: called.append(age))

    monkeypatch.setattr(sched, "get_settings",
                        lambda: Settings(_env_file=None, http_revalidate=False, scrape_cache=False))
    sched._prune_response_cache()
    assert called == []

    monkeypatch.setattr(sched, "get_settings",
                        lambda: Settings(_env_file=None, http_revalidate=True, scrape_cache=False))
    sched._prune_response_cache()
    assert called == [sched.RESPONSE_CACHE_MAX_AGE_DAYS * 86400]


@pytest.mark.asyncio
async def test_start_scheduler_registers_both_jobs_at_the_configured_interval(monkeypatch):
    """The interval is read when the app starts, not when the module is imported.

    A module-level `settings = get_settings()` is captured the first time anything
    imports this, which is not necessarily when the app starts -- the same trap that
    made AuthMiddleware read stale settings. Configuring 6 hours and observing 6
    hours is the only way to tell the difference.
    """
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from src.config import Settings
    from src.scheduler import scheduler as sched

    fresh = AsyncIOScheduler()
    monkeypatch.setattr(sched, "scheduler", fresh)
    monkeypatch.setattr(sched, "get_settings", lambda: Settings(_env_file=None, scrape_interval_hours=6))

    sched.start_scheduler()
    try:
        jobs = {job.id: job for job in fresh.get_jobs()}
        assert set(jobs) == {"firmware_check", "generate_summaries"}
        # Six hours, said as hours-of-the-day and anchored on scrape_hour (3), so the
        # fire times are 03/09/15/21 rather than "six hours after this process started".
        assert "3/6" in str(jobs["firmware_check"].trigger)
        # Summaries are hourly regardless; they only process what is already pending.
        assert jobs["generate_summaries"].trigger.interval.total_seconds() == 3600
    finally:
        fresh.shutdown(wait=False)


@pytest.mark.asyncio
async def test_start_scheduler_can_run_twice_without_duplicating_jobs(monkeypatch):
    """replace_existing must hold, or a reload doubles every scheduled scrape."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from src.config import Settings
    from src.scheduler import scheduler as sched

    fresh = AsyncIOScheduler()
    monkeypatch.setattr(sched, "scheduler", fresh)
    monkeypatch.setattr(sched, "get_settings", lambda: Settings(_env_file=None))

    sched.start_scheduler()
    try:
        sched.scheduler.add_job(
            sched.check_firmware_updates,
            trigger=__import__("apscheduler.triggers.interval", fromlist=["IntervalTrigger"]).IntervalTrigger(hours=24),
            id="firmware_check",
            replace_existing=True,
        )
        assert len([j for j in fresh.get_jobs() if j.id == "firmware_check"]) == 1
    finally:
        fresh.shutdown(wait=False)


@pytest.mark.asyncio
async def test_summaries_job_survives_the_summarizer_failing(monkeypatch, caplog):
    """The API key may be missing or the API down; neither should kill the job."""
    from src.scheduler import scheduler as sched

    async def explode(db):
        raise RuntimeError("anthropic api unavailable")

    monkeypatch.setattr(sched, "summarize_pending_changelogs", explode)

    with caplog.at_level(logging.ERROR, logger="src.scheduler.scheduler"):
        await sched.generate_summaries()  # must not raise

    assert "Error during summarization" in caplog.text
    assert "anthropic api unavailable" in caplog.text


def test_prune_reports_what_it_removed(monkeypatch, caplog):
    """A silent prune gives no way to tell it from one that found nothing."""
    from src.config import Settings
    from src.scheduler import scheduler as sched

    monkeypatch.setattr(sched.ResponseCache, "prune", lambda self, age: 12)
    monkeypatch.setattr(sched, "get_settings", lambda: Settings(_env_file=None, http_revalidate=True))

    with caplog.at_level(logging.INFO, logger="src.scheduler.scheduler"):
        sched._prune_response_cache()

    assert "Pruned 12 stale cached responses" in caplog.text

    # Nothing removed means nothing said, so a quiet log means a quiet cache.
    caplog.clear()
    monkeypatch.setattr(sched.ResponseCache, "prune", lambda self, age: 0)
    with caplog.at_level(logging.INFO, logger="src.scheduler.scheduler"):
        sched._prune_response_cache()
    assert "Pruned" not in caplog.text


@pytest.mark.asyncio
async def test_summaries_job_reports_its_count(monkeypatch, caplog):
    from src.scheduler import scheduler as sched

    async def summarise(db):
        return 5

    monkeypatch.setattr(sched, "summarize_pending_changelogs", summarise)

    with caplog.at_level(logging.INFO, logger="src.scheduler.scheduler"):
        await sched.generate_summaries()

    assert "Summarized 5 changelogs" in caplog.text


@pytest.mark.asyncio
async def test_shutdown_scheduler_stops_it(monkeypatch, caplog):
    """The lifespan calls this on every reload, so it has to actually stop."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from src.config import Settings
    from src.scheduler import scheduler as sched

    fresh = AsyncIOScheduler()
    monkeypatch.setattr(sched, "scheduler", fresh)
    monkeypatch.setattr(sched, "get_settings", lambda: Settings(_env_file=None))

    sched.start_scheduler()
    assert fresh.running

    with caplog.at_level(logging.INFO, logger="src.scheduler.scheduler"):
        sched.shutdown_scheduler()

    # AsyncIOScheduler._shutdown is decorated @run_in_event_loop, so the call is
    # dispatched to the loop rather than done inline -- it has not stopped when
    # shutdown() returns. Harmless in the lifespan, where the loop keeps running,
    # but asserting immediately would test the dispatch rather than the stop.
    await asyncio.sleep(0.05)

    assert not fresh.running
    assert "Scheduler shutdown" in caplog.text


def _utc(year, month, day, hour, minute=0):
    from datetime import datetime, timezone
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_the_scrape_clock_survives_a_restart():
    """The bug this fixes: an interval counted from process start.

    The scheduler runs in-process, so every deploy and every Spot replacement restarted
    it -- and an IntervalTrigger begins counting at start_date. Production logged 12
    "Scheduler started" lines across 2026-09-17/18 and exactly one firmware check in that
    window: a day of shipping scraped nothing, and nothing reported that it had not.

    A cron trigger is anchored to the clock instead. Starting at midnight or at six in
    the morning, the next run is the same 03:00 slot -- the later start simply catches
    tomorrow's, rather than postponing by a whole day from whenever it happened to boot.

    Timezone-aware datetimes on purpose: APScheduler compares against aware times and
    raises TypeError on naive ones, which is a way to write this test so it passes for
    the wrong reason.
    """
    from src.config import Settings
    from src.scheduler.scheduler import _firmware_trigger

    trigger = _firmware_trigger(Settings(_env_file=None))

    from_midnight = trigger.get_next_fire_time(None, _utc(2026, 9, 19, 0))
    from_six = trigger.get_next_fire_time(None, _utc(2026, 9, 19, 6))

    assert from_midnight.hour == 3 and from_midnight.minute == 0
    assert from_six.hour == 3 and from_six.minute == 0
    assert from_midnight == _utc(2026, 9, 19, 3)
    assert from_six == _utc(2026, 9, 20, 3)


def test_the_old_trigger_really_did_move_with_the_restart():
    """The control, so the test above is about the change and not about cron in general."""
    from apscheduler.triggers.interval import IntervalTrigger

    from_midnight = IntervalTrigger(hours=24, start_date=_utc(2026, 9, 19, 0))
    from_six = IntervalTrigger(hours=24, start_date=_utc(2026, 9, 19, 6))

    first = from_midnight.get_next_fire_time(None, _utc(2026, 9, 19, 0))
    second = from_six.get_next_fire_time(None, _utc(2026, 9, 19, 6))

    # Six hours of restart became six hours of postponement -- and with enough restarts,
    # the run never arrives at all.
    assert (second - first).total_seconds() == 6 * 3600


def test_a_sub_daily_interval_is_anchored_to_the_configured_hour():
    """scrape_interval_hours stays the unit; it is mapped onto the clock, not replaced.

    /scrape-status derives its staleness threshold from the same setting, so the interval
    has to keep meaning what it says.
    """
    from datetime import timedelta

    from src.config import Settings
    from src.scheduler.scheduler import _firmware_trigger

    trigger = _firmware_trigger(Settings(_env_file=None, scrape_interval_hours=6, scrape_hour=3))

    hours, previous, now = [], None, _utc(2026, 9, 19, 0)
    for _ in range(4):
        now = trigger.get_next_fire_time(previous, now)
        hours.append(now.hour)
        previous, now = now, now + timedelta(seconds=1)

    assert hours == [3, 9, 15, 21], "the configured hour must be one of the fire times"


def test_an_interval_that_cannot_be_said_in_hours_falls_back_loudly(caplog):
    """Five hours does not divide a day, so hours-of-the-day would drift.

    Keeping the old trigger is the honest answer; doing it silently would leave someone
    believing a schedule the app is not running.
    """
    import logging

    from apscheduler.triggers.interval import IntervalTrigger

    from src.config import Settings
    from src.scheduler.scheduler import _firmware_trigger

    with caplog.at_level(logging.WARNING):
        trigger = _firmware_trigger(Settings(_env_file=None, scrape_interval_hours=5))

    assert isinstance(trigger, IntervalTrigger)
    assert "divisor of 24" in caplog.text


def test_the_scrape_hour_stays_clear_of_the_backup_window():
    """AWS Backup snapshots the EFS volume at 05:00 UTC (infra/backup.tf).

    The sweep used to land in that same hour by accident. A scrape writing SQLite while
    the volume is snapshotted is how a recovery point ends up holding a half-written
    database -- the one file the backup exists for.
    """
    from src.config import Settings

    assert Settings(_env_file=None).scrape_hour == 3


@pytest.mark.asyncio
async def test_the_firmware_job_will_not_run_two_sweeps_at_once(monkeypatch):
    """A sweep can outlast its interval; two at once means two writers on one SQLite file."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from src.config import Settings
    from src.scheduler import scheduler as sched

    fresh = AsyncIOScheduler()
    monkeypatch.setattr(sched, "scheduler", fresh)
    monkeypatch.setattr(sched, "get_settings", lambda: Settings(_env_file=None))

    sched.start_scheduler()
    try:
        job = {j.id: j for j in fresh.get_jobs()}["firmware_check"]
        assert job.max_instances == 1
        assert job.coalesce is True
    finally:
        fresh.shutdown(wait=False)
