"""One place that decides where this application's log output goes.

Nothing configured logging before this, and the effect was quietly lopsided. Python
installs a `lastResort` handler that emits WARNING and above to stderr, so the auth
warning at startup appeared and every INFO message did not -- including the scheduler
announcing its interval, which is the one line that tells you whether the app is
going to scrape once a day or four times.

Meanwhile the scraping path used `print()`, so its output carried no level, no
timestamp and no module name, and could not be filtered or silenced.
"""

import logging
import logging.handlers
import sys
from pathlib import Path

from src.config import Settings

FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Paths whose access lines say nothing. The container health check polls /health
# every 30 seconds, which is 2,880 requests a day and about 95MB of access log a
# year -- against roughly 1MB of actual scrape results. Left in, rotation would
# mostly be rotating this.
HEALTH_PATHS = ("/health", "/health/ready")


class _DropHealthCheckAccess(logging.Filter):
    """Drop uvicorn access lines for the health endpoints.

    uvicorn logs access as '%s - "%s %s HTTP/%s" %d' with the path as the third
    argument, so the path is read from there rather than by matching the formatted
    line -- a substring test against the whole message would also drop a request
    whose query string happened to mention /health.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) < 3:
            return True
        path = str(args[2]).split("?", 1)[0]
        return path not in HEALTH_PATHS


def configure_logging(settings: Settings) -> None:
    """Point this application's log output at stderr, and keep it readable.

    Safe to call repeatedly: the lifespan runs again on every reload. Only creating
    the handler is guarded -- everything else is reapplied, because an early return
    would mean a changed LOG_LEVEL or LOG_HEALTH_CHECKS never took effect on a
    reload while appearing to.
    """
    root = logging.getLogger()
    level = _level(settings)

    if not any(getattr(h, "_firmware_tracker", False) for h in root.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(FORMAT, DATE_FORMAT))
        handler._firmware_tracker = True  # marks it as ours, so a reload reuses it
        root.addHandler(handler)

    _configure_file_handler(root, settings)

    root.setLevel(level)
    for handler in root.handlers:
        if getattr(handler, "_firmware_tracker", False):
            handler.setLevel(level)

    # These drown out the application at the level people actually set them to.
    # APScheduler narrates every job submission at INFO, and asyncio, aiohttp and
    # Playwright each produce hundreds of DEBUG lines about their own internals --
    # which is not what someone raising LOG_LEVEL to DEBUG is trying to see.
    for noisy in ("apscheduler", "asyncio", "aiohttp", "playwright", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    access = logging.getLogger("uvicorn.access")
    for existing in list(access.filters):
        if isinstance(existing, _DropHealthCheckAccess):
            access.removeFilter(existing)
    if not settings.log_health_checks:
        access.addFilter(_DropHealthCheckAccess())

    # uvicorn's loggers are otherwise left alone. The `uvicorn` logger owns the
    # handler and already has propagate=False, so its records never reach the root
    # handler added above and nothing is printed twice. `uvicorn.error` has no
    # handler of its own and depends on propagating up to `uvicorn` -- setting
    # propagate=False on it, which looks like the obvious way to prevent duplicates,
    # instead sends its records nowhere and silently loses "Application startup
    # complete" along with every startup error.


def _configure_file_handler(root: logging.Logger, settings: Settings) -> None:
    """Add, replace or remove the rotating file handler to match LOG_FILE.

    Rotation lives here rather than being left to the supervisor because the common
    way to run this outside a container -- `uvicorn ... > file &` -- has no
    supervisor, and that file grows until the disk does. Under Docker and systemd
    LOG_FILE stays empty and both capture stderr as usual.
    """
    existing = next(
        (h for h in root.handlers if getattr(h, "_firmware_tracker_file", False)), None
    )
    target = str(settings.log_file or "").strip()

    if not target:
        if existing:
            root.removeHandler(existing)
            existing.close()
        return

    # Reuse the handler when the destination and limits are unchanged, so a reload
    # does not reopen the file or start a second rotation sequence against it.
    if existing and (
        existing.baseFilename == str(Path(target).expanduser().resolve())
        and existing.maxBytes == settings.log_max_bytes
        and existing.backupCount == settings.log_backup_count
    ):
        return

    if existing:
        root.removeHandler(existing)
        existing.close()

    path = Path(target).expanduser()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            path,
            maxBytes=settings.log_max_bytes,
            backupCount=settings.log_backup_count,
            encoding="utf-8",
        )
    except OSError as exc:
        # An unwritable path must not stop the app booting. stderr is already
        # attached, so the warning is seen.
        logging.getLogger(__name__).warning(
            "Could not open log file %s (%s); logging to stderr only", path, exc
        )
        return

    handler.setFormatter(logging.Formatter(FORMAT, DATE_FORMAT))
    handler._firmware_tracker = True
    handler._firmware_tracker_file = True
    root.addHandler(handler)


def _level(settings: Settings) -> int:
    """Resolve LOG_LEVEL, falling back to INFO rather than failing to start."""
    named = logging.getLevelName(str(settings.log_level).upper())
    return named if isinstance(named, int) else logging.INFO
