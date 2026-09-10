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
import sys

from src.config import Settings

FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(settings: Settings) -> None:
    """Attach a stderr handler to the root logger, once.

    Idempotent because the lifespan runs again on every reload, and a second handler
    means every line printed twice.
    """
    root = logging.getLogger()

    for handler in root.handlers:
        if getattr(handler, "_firmware_tracker", False):
            handler.setLevel(_level(settings))
            root.setLevel(_level(settings))
            return

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(FORMAT, DATE_FORMAT))
    handler._firmware_tracker = True  # marks it as ours, so a reload replaces it

    root.addHandler(handler)
    root.setLevel(_level(settings))

    # These drown out the application at the level people actually set them to.
    # APScheduler narrates every job submission at INFO, and asyncio, aiohttp and
    # Playwright each produce hundreds of DEBUG lines about their own internals --
    # which is not what someone raising LOG_LEVEL to DEBUG is trying to see.
    for noisy in ("apscheduler", "asyncio", "aiohttp", "playwright", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # uvicorn's loggers are deliberately left alone. The `uvicorn` logger owns the
    # handler and already has propagate=False, so its records never reach the root
    # handler added above and nothing is printed twice. `uvicorn.error` has no
    # handler of its own and depends on propagating up to `uvicorn` -- setting
    # propagate=False on it, which looks like the obvious way to prevent duplicates,
    # instead sends its records nowhere and silently loses "Application startup
    # complete" along with every startup error.


def _level(settings: Settings) -> int:
    """Resolve LOG_LEVEL, falling back to INFO rather than failing to start."""
    named = logging.getLevelName(str(settings.log_level).upper())
    return named if isinstance(named, int) else logging.INFO
