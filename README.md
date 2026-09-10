# Firmware Tracker

[![CI](https://github.com/gmoynihan88/firmware_tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/gmoynihan88/firmware_tracker/actions/workflows/ci.yml)

A self-hosted web app that scrapes manufacturer websites for firmware and software updates across music production hardware and VST plugins. Track your gear, get notified when updates drop.

![The dashboard, filtered to devices with updates available](docs/images/dashboard.png)

*The dashboard, filtered to devices with an update waiting. Filter by status, brand or type; sort any column.*

## What it does

- **Scrapes 22 manufacturers** for firmware/version data (Boss, Elektron, Focusrite, Moog, Native Instruments, Strymon, Universal Audio, and more)
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

> **Note:** the app ships with no authentication. Keep it bound to localhost or put it behind an authenticating reverse proxy — see [Security](#security).

## Configuration

Copy `.env.example` to `.env` (or export the variables):

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./firmware_tracker.db` | Database connection string |
| `ANTHROPIC_API_KEY` | *(optional)* | Enables AI changelog summarization |
| `SCRAPE_INTERVAL_HOURS` | `24` | How often the scheduler checks for updates |
| `SCRAPE_CACHE` | `false` | Development only: cache scraped responses on disk |
| `SCRAPE_CACHE_TTL_HOURS` | `6` | How long a cached response stays usable |
| `NOTIFY_TRANSPORT` | `none` | Where to deliver notifications: `none` or `ntfy` |
| `NTFY_TOPIC` | *(none)* | ntfy topic to publish to; required when transport is `ntfy` |
| `NTFY_SERVER` | `https://ntfy.sh` | ntfy server, for self-hosting |
| `AUTH_PASSWORD_HASH` | *(none)* | Enables authentication; generate with `python -m src.auth.hash_password` |
| `SECRET_KEY` | *(none)* | Signs session cookies; rotating it logs everyone out |
| `API_KEY` | *(none)* | Optional `X-API-Key` for scripts |
| `SESSION_LIFETIME_HOURS` | `336` | How long a login lasts (14 days) |
| `DEBUG` | `false` | Development mode |
| `REQUEST_TIMEOUT` | `30` | Seconds before a scraper HTTP request gives up |
| `RATE_LIMIT_DELAY` | `1.0` | Seconds between requests to the same manufacturer |

## Security

**Authentication is off until you configure it.** Generate a password hash and a
secret key, and put both in `.env`:

```bash
python -m src.auth.hash_password
```

The app warns at startup while it is unconfigured, naming what is exposed. With it
on, everything requires a session except `/health`, `/health/ready`, `/login` and
`/static` — a load balancer cannot present credentials, and requiring auth to reach
the login form is a redirect loop.

Scripts can send `X-API-Key` instead of logging in, if `API_KEY` is set. An unset
`API_KEY` means the header is ignored entirely, not that any key works.

Passwords are hashed with scrypt and sessions are signed with HMAC, both from the
standard library — no additional dependencies.

**Without it, every route is open** to anyone who can reach the port, including the
write endpoints:

- `POST /api/firmware/scrape-all` and `POST /api/firmware/scrape/{manufacturer}` — anyone
  who can reach the server can trigger outbound scraping of 20 manufacturer sites, which
  is both slow and a good way to get your IP rate-limited
- `POST`/`PATCH`/`DELETE` on `/api/manufacturers`, `/api/device-models`, `/api/my-devices` —
  full unauthenticated CRUD over your tracked gear

That default keeps a local install working with no setup, and is fine on localhost.
Configure authentication before putting this on a public address.

Also worth knowing:

- `ANTHROPIC_API_KEY` is read from `.env`, which is gitignored. Keep it that way.
- **On public ntfy.sh the topic name is the only secret.** Anyone who knows or guesses
  it can read your notifications and publish to them, so use a long random value
  (`firmware-tracker-$(openssl rand -hex 16)`) and keep it in `.env`. Self-host ntfy
  with auth if that is not good enough for you.
- Scrapers rate-limit themselves via `RATE_LIMIT_DELAY` and send a browser
  `User-Agent`. See [Being a good neighbour](#being-a-good-neighbour-to-the-vendors).

## Being a good neighbour to the vendors

Several of the sites this scrapes are run by very small outfits — Sound-Force and TAL
are effectively one-person operations — so the defaults are set to cost them as little
as possible, and it is worth keeping them that way if you fork this.

- Scrapers rate-limit themselves to one request per second via `RATE_LIMIT_DELAY`.
- `SCRAPE_INTERVAL_HOURS` defaults to **24**. Firmware ships a few times a year;
  checking more often multiplies the load without finding anything sooner.
- **Set `SCRAPE_CACHE=1` while developing.** Working on a scraper means running the
  same fetch over and over against data that has not changed, and without a cache the
  vendor serves every one of those. Responses are stored under `.scrape_cache/` for
  `SCRAPE_CACHE_TTL_HOURS`, keyed on the full request. It is off by default and should
  stay off in normal use — a cached run cannot discover a new firmware version.
- Scrapers currently send a browser `User-Agent`, because some vendors reject
  non-browser clients outright. The trade-off is that they cannot tell who is calling
  or ask you to stop, which is not ideal; an identifying UA with per-scraper overrides
  is the better end state.

One thing to know if this ever spreads: every instance scrapes independently, so N
users means N times the load on those same small sites. A shared cache would be the
neighbourly answer at that point.

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

A scrape reports what it could not do, not just what it did:

```json
{
  "new_firmware_versions": 195,
  "devices_without_firmware": ["Hall of Fame 2"],
  "devices_failed": [],
  "devices_not_checked": []
}
```

`devices_without_firmware` are products the manufacturer publishes no firmware for —
a verified fact, not a failure. `devices_failed` is a fetch or parse that broke.
`devices_not_checked` is the time budget running out before reaching them.

Scraping only raises notifications for versions it discovers, so a device whose
installed version you record *after* its latest is already known would never get one.
This fills those in, and is safe to re-run — one notification per device per version:

```bash
curl -X POST http://localhost:8000/api/firmware/reconcile-notifications
```

### Notifications

Notifications are always recorded and shown at `/notifications`. To have them pushed
to your phone as well, set a transport:

```bash
# .env
NOTIFY_TRANSPORT=ntfy
NTFY_TOPIC=firmware-tracker-<long random string>
```

Subscribe to the same topic in the [ntfy app](https://ntfy.sh/app) or at
`https://ntfy.sh/<your-topic>`. Delivery is a side effect of recording a
notification: if the transport is unreachable the notification is still stored, and
the failure is logged rather than raised.

**The test suite never delivers.** `tests/conftest.py` forces the transport off, so
running `pytest` on a machine with ntfy configured cannot push fixture notifications
to your phone.

**Silencing a manual run.** Environment variables take precedence over `.env`, so
prefix anything you are only running to inspect output:

```bash
NOTIFY_TRANSPORT=none .venv/bin/python -c "...trigger a scrape..."
```

Worth doing while debugging a scraper: a scrape that finds versions for a device you
track will notify, and repeated runs are how a phone ends up full of the same alert.

### Health checks

Two endpoints, for container orchestration:

```bash
curl http://localhost:8000/health        # liveness  -> {"status":"ok","uptime_seconds":2.9}
curl http://localhost:8000/health/ready  # readiness -> {"status":"ok","database":"ok"}
```

`/health` touches nothing and always answers, so a failure means the process is
wedged or gone. It deliberately does not check the database: if it did, a slow disk
would have the orchestrator kill and replace tasks, which does not fix a slow disk.

`/health/ready` runs a trivial query and returns **503** with a reason when the
database is unreachable. On a deployment where the database is a file on a network
mount, losing that mount is exactly what this catches.

Both sit outside `/api` and take no authentication — a load balancer cannot present
credentials, and a 200 here discloses nothing.

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
| Elektron | iZotope |
| Focusrite | Modartt (Pianoteq) |
| Line 6 | Moog |
| Peterson | Native Instruments |
| QSC | Steinberg |
| Roland | TAL Software |
| Sound-Force | Universal Audio |
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

Return `success=False` when a fetch or parse breaks, and `success=True` with an empty
list when the page loaded and the product genuinely has no firmware. Some products
ship none at all, so the two are not the same thing and the scrape summary reports
them separately.

### Claude Code skills

`.claude/skills/` carries two skills for this work:

- **`add-scraper`** — conventions for a new plugin.
- **`debug-scraper`** — a diagnostic ladder for a scraper returning nothing or
  reporting versions that do not match the vendor. Worth reading before rewriting a
  parser: the cause is usually a dead URL or a moved data source. Manufacturers
  restructure their sites regularly, and several have replaced HTML pages with JSON
  APIs that the page itself calls.

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
    plugins/           # One file per manufacturer (21 scrapers)
  notifications/
    transport.py       # Delivery to ntfy, behind a Notifier protocol
    reconcile.py       # Raises notifications for devices behind their latest
  scheduler/           # APScheduler periodic checks
  summarizer/          # Optional Claude API changelog summaries
.claude/skills/        # Claude Code skills for adding and debugging scrapers
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
