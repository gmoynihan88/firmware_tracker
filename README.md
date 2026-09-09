# Firmware Tracker

A self-hosted web app that scrapes manufacturer websites for firmware and software updates across music production hardware and VST plugins. Track your gear, get notified when updates drop.

## What it does

- **Scrapes 20 manufacturers** for firmware/version data (Boss, Elektron, Focusrite, Moog, Native Instruments, Strymon, Universal Audio, and more)
- **Tracks your devices** — add hardware and plugins you own, see at a glance what's current and what has updates
- **Scans installed VST/AU/CLAP plugins** on macOS and matches them against the database
- **Scheduled checks** — APScheduler runs periodic scrapes in the background
- **AI changelog summaries** — optional Anthropic Claude integration to summarize firmware changelogs

## Quick start

Requires Python 3.11+.

```bash
# Clone and install
git clone https://github.com/gmoynihan88/firmware_tracker.git
cd firmware_tracker
pip install -e ".[dev]"

# Optional: install Playwright for JS-rendered scraper pages
pip install -e ".[browser]" && playwright install chromium

# Initialize the database
alembic upgrade head

# Start the server
uvicorn src.main:app --reload
```

Open http://localhost:8000.

## Configuration

Copy `.env.example` to `.env` (or export the variables):

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./firmware_tracker.db` | Database connection string |
| `ANTHROPIC_API_KEY` | *(optional)* | Enables AI changelog summarization |
| `CHECK_INTERVAL_HOURS` | `24` | How often the scheduler checks for updates |

## Usage

### Dashboard

The main page shows all your tracked devices with their installed vs. latest firmware versions. Filter by device type, brand, or update status.

### Adding devices

Browse the catalog at `/catalog`, or use the plugin scanner to bulk-import from your system:

```bash
# See what plugins are installed and which match the database
python scripts/scan_installed_plugins.py --compare

# Import matched plugins to your tracked devices
python scripts/scan_installed_plugins.py --add
```

### Running scrapers

Scrape all manufacturers via the API:

```bash
curl -X POST http://localhost:8000/api/firmware/scrape-all
```

Or scrape a single manufacturer:

```bash
curl -X POST http://localhost:8000/api/firmware/scrape/strymon
```

### Database backup

```bash
# Snapshot (safe while server is running)
bash scripts/backup_db.sh

# List backups
bash scripts/backup_db.sh list

# Restore
bash scripts/backup_db.sh restore backups/firmware_tracker_YYYYMMDD_HHMMSS.db
```

## Supported manufacturers

| Hardware | VST Plugins |
|---|---|
| Boss | GForce Software |
| Crumar | IK Multimedia |
| Elektron | Modartt (Pianoteq) |
| Focusrite | Moog |
| Line 6 | Native Instruments |
| Peterson | TAL Software |
| QSC | Universal Audio |
| Roland | |
| Sound-Force | |
| Strymon | |
| TC Electronic | |
| Tascam | |
| Yamaha | |

## Adding a new scraper

Create a file in `src/scrapers/plugins/` that subclasses `BaseScraper`:

```python
from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

class MyScraper(BaseScraper):
    manufacturer_name = "Acme Audio"
    manufacturer_slug = "acme"
    manufacturer_website = "https://acme.example.com"

    async def fetch_device_list(self) -> ScraperResult:
        # Return ScraperResult with list of ScrapedDevice
        ...

    async def fetch_firmware_versions(self, device_name, firmware_page_url) -> ScraperResult:
        # Return ScraperResult with list of ScrapedFirmware
        ...
```

It's auto-discovered on startup — no registration needed. Add an assertion for the new slug in `tests/test_basic.py::test_api_scrapers`.

## Project structure

```
src/
  main.py              # FastAPI app, lifespan, router registration
  config.py            # Pydantic Settings from .env
  database.py          # Async SQLAlchemy engine + session factory
  devices/             # Models, schemas, CRUD service, REST router
  firmware/            # Scrape trigger API endpoints
  web/                 # Jinja2 HTML page routes
  scrapers/
    base.py            # BaseScraper with aiohttp + Playwright helpers
    registry.py        # Auto-discovery via pkgutil
    service.py         # Orchestrates scrape → sync → notify
    plugins/           # One file per manufacturer (20 scrapers)
  scheduler/           # APScheduler periodic checks
  summarizer/          # Optional Claude API changelog summaries
templates/             # Jinja2 templates
static/css/            # Stylesheets
scripts/               # Plugin scanner, backup, utilities
tests/                 # pytest-asyncio with in-memory SQLite
```

## Development

```bash
# Run tests
pytest

# Run tests with coverage
pytest --cov=src tests/

# Run a single test
pytest tests/test_basic.py::test_dashboard
```

Tests use an in-memory SQLite database and never touch the production DB.

## License

MIT
