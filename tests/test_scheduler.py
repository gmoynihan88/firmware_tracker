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
        assert jobs["firmware_check"].trigger.interval.total_seconds() == 6 * 3600
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
