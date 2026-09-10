from pydantic_settings import BaseSettings
from functools import lru_cache
from pathlib import Path


class Settings(BaseSettings):
    app_name: str = "Firmware Tracker"
    debug: bool = False

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
    request_timeout: int = 30
    rate_limit_delay: float = 1.0  # seconds between requests per manufacturer

    # An on-disk response cache for development only, off by default so production
    # always fetches live. Debugging a scraper means running it repeatedly against
    # data that has not changed; SCRAPE_CACHE=1 makes those repeats hit disk instead
    # of the vendor. See src/scrapers/cache.py.
    scrape_cache: bool = False
    scrape_cache_ttl_hours: float = 6.0

    # Paths
    base_dir: Path = Path(__file__).parent.parent
    templates_dir: Path = base_dir / "templates"
    static_dir: Path = base_dir / "static"
    scrape_cache_dir: Path = base_dir / ".scrape_cache"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
