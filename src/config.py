from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from pathlib import Path


class Settings(BaseSettings):
    app_name: str = "Firmware Tracker"
    debug: bool = False

    # Declared only so the documented setup starts. The app never binds this: uvicorn's
    # port comes from its command line, and docker-compose publishes with
    # `"${PORT:-8000}:8000"` -- compose interpolates PORT from the same .env file the
    # app reads, which is the arrangement .env.example's own header describes.
    #
    # One file, two consumers, opposite rules. pydantic-settings defaults BaseSettings
    # to extra="forbid" -- it is not written anywhere in this file, which is why
    # grepping for "forbid" finds nothing -- so a key compose needs and the app has not
    # declared is a ValidationError at import, before any of it runs. `cp .env.example
    # .env` therefore could not start, and only a developer .env that predated the PORT
    # line hid it.
    #
    # Declaring the field is the narrow fix. extra="ignore" would also stop the crash
    # and would stop catching typos in every other setting here, turning a misspelled
    # SCRAPE_INTERVAL_HOURS into a silent default.
    port: int = 8000

    # INFO shows scrape results and the scheduler's interval; DEBUG adds every fetch.
    # Without a configured handler Python's lastResort emits only WARNING and above,
    # so INFO vanishes silently -- see src/logging_config.py.
    log_level: str = "INFO"

    # Access lines for /health are dropped by default. A container health check polls
    # it every 30 seconds, which would be about 95MB of access log a year against
    # roughly 1MB of scrape results. Set true when debugging the check itself.
    log_health_checks: bool = False

    # Optional rotating file log, in addition to stderr. Empty means stderr only,
    # which is right under Docker and systemd because both already capture and
    # rotate it. Set a path when running the server directly -- `uvicorn > file &`
    # has nothing rotating it, and that file grows until the disk does.
    log_file: str = ""
    log_max_bytes: int = 10_000_000
    log_backup_count: int = 3

    # Database
    database_url: str = "sqlite+aiosqlite:///./firmware_tracker.db"

    # Anthropic API
    anthropic_api_key: str = ""

    # Authentication. Disabled when auth_password_hash is empty, which keeps a local
    # install working with no setup -- the app warns loudly at startup in that state,
    # because every write endpoint is open without it.
    auth_password_hash: str = ""      # generate with: python -m src.auth.hash_password
    secret_key: str = ""              # signs session cookies; rotating it logs everyone out
    api_key: str = ""                 # optional, for X-API-Key on programmatic calls
    session_lifetime_hours: int = 336  # 14 days

    # Marks the session cookie Secure regardless of the scheme the app sees. CloudFront
    # and API Gateway terminate TLS and speak http to the task, so the scheme alone
    # drops the flag exactly where it matters. Set true in any deployment reached over
    # https; left false so a plain http://localhost install still keeps its session.
    session_cookie_secure: bool = False

    # Serve the catalogue to anonymous visitors: vendor data, not personal. The
    # dashboard, notifications, tracked devices and every write stay behind the
    # password. Off by default so a local install is private until it is deliberately
    # shared.
    public_catalog: bool = False

    # Failed logins allowed per client address within the window, after which /login
    # answers 429 with Retry-After. A correct password clears the count. See
    # src/auth/throttle.py: behind a proxy uvicorn needs --proxy-headers, or every
    # request looks like one client.
    login_max_attempts: int = 5
    login_window_seconds: int = 300

    # Notification delivery. Transport is "none" by default so the app runs with no
    # configuration; on public ntfy.sh the topic name is the only secret, so use a
    # long random one and keep it in .env.
    notify_transport: str = "none"  # none | ntfy
    ntfy_topic: str = ""
    ntfy_server: str = "https://ntfy.sh"

    # Scraping settings
    #
    # Firmware ships a few times a year, so checking once a day is already far more
    # often than the data changes. Four times a day cost the vendors four times as
    # much for nothing.
    scrape_interval_hours: int = 24

    # The wall-clock hour, UTC, that the firmware check runs at -- and the anchor for
    # sub-daily intervals, so 6 hours means 03:00/09:00/15:00/21:00 rather than "six
    # hours after whenever this process happened to start".
    #
    # 03:00 avoids 05:00 on purpose: AWS Backup snapshots the EFS volume at 05:00 UTC
    # (infra/backup.tf), and the sweep used to land in that same hour. A scrape writing
    # SQLite while the volume is being snapshotted is how a recovery point ends up
    # holding a half-written database, which is the one file the backup exists for.
    scrape_hour: int = 3
    request_timeout: int = 30
    rate_limit_delay: float = 1.0  # seconds between requests per manufacturer

    # The largest body any vendor has returned is about 4 MB. A response past this is
    # not a firmware page, and reading it whole would spend its size in memory. See
    # src/scrapers/netguard.py.
    max_response_bytes: int = 25_000_000

    # An on-disk response cache for development only, off by default so production
    # always fetches live. Debugging a scraper means running it repeatedly against
    # data that has not changed; SCRAPE_CACHE=1 makes those repeats hit disk instead
    # of the vendor. See src/scrapers/cache.py.
    scrape_cache: bool = False
    scrape_cache_ttl_hours: float = 6.0

    # Conditional requests, on by default. Each response's ETag/Last-Modified is kept
    # and sent back as If-None-Match/If-Modified-Since, so an unchanged page answers
    # 304 with no body. Only about a quarter of the tracked vendors send a validator,
    # so this is a partial saving -- see src/scrapers/cache.py.
    http_revalidate: bool = True

    # Paths
    base_dir: Path = Path(__file__).parent.parent
    templates_dir: Path = base_dir / "templates"
    static_dir: Path = base_dir / "static"
    scrape_cache_dir: Path = base_dir / ".scrape_cache"

    # `class Config` was deprecated in Pydantic V2.0 and is removed in V3, and it warned
    # on every run. src/devices/schemas.py already uses the replacement, so this was the
    # last one. Behaviour is unchanged: the same two settings, expressed the current way.
    #
    # extra="forbid" is stated rather than inherited. It is the pydantic-settings default
    # and was never written down, which is exactly how #226 became hard to believe: the
    # documented `cp .env.example .env` raised ValidationError on an undeclared PORT, and
    # anyone grepping this file for "forbid" found nothing and could reasonably conclude
    # the report was wrong. Saying it also pins the behaviour against a future change of
    # that default -- silently flipping to "ignore" would turn a misspelled
    # SCRAPE_INTERVAL_HOURS into a default nobody chose. tests/test_config.py holds it.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
