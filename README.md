# Firmware Tracker

[![CI](https://github.com/gmoynihan88/firmware_tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/gmoynihan88/firmware_tracker/actions/workflows/ci.yml)

Music gear ships firmware updates and then never mentions it again. There is no feed,
no notification, no changelog you can subscribe to — just a downloads page per vendor
that you are expected to remember to visit. Miss one and you find out months later,
usually mid-session, usually because of the bug it fixed.

This tracks 23 manufacturers so you don't have to. It scrapes their sites, notices
when something you own falls behind, and tells you.

![The dashboard, filtered to devices with updates available](docs/images/dashboard.png)

*Filtered to devices with an update waiting. Sort any column; filter by status, brand or type.*

## Quick start

```bash
git clone https://github.com/gmoynihan88/firmware_tracker.git
cd firmware_tracker
docker compose up
```

Open http://localhost:8000. Nothing to configure — it starts with no notifications, no
AI summaries and no authentication, which is fine on localhost.

**On a Mac, try the plugin scanner first.** No server, no database, no commitment — it
reads your VST3, VST, AU and CLAP folders and tells you what you actually have:

```bash
python scripts/scan_installed_plugins.py
```

Most people have no idea what is in there.

<details>
<summary>Running it without Docker</summary>

Requires Python 3.11+.

```bash
pip install -e ".[dev]"
pip install -e ".[browser]" && playwright install chromium   # 10 scrapers need a browser
alembic upgrade head
uvicorn src.main:app --reload
```
</details>

## What it does

- **Scrapes 23 manufacturers** — Boss, Elektron, Eventide, Focusrite, iZotope, Moog,
  Native Instruments, Steinberg, Strymon, Universal Audio and more
- **Tracks hardware and plugins together**, rather than one or the other
- **Scans installed plugins** on macOS and matches them to the catalogue
- **Checks daily** and pushes to [ntfy](https://ntfy.sh) when something falls behind
- **Optional AI changelog summaries** via the Anthropic API

## The interesting part: it admits what it doesn't know

Scraping 23 vendors means 23 sites that change without warning, and the tempting
failure is to quietly invent data rather than report a gap.

Universal Audio is the cautionary tale. Its scraper looked like the healthiest in the
repo — ran in 0.01s, never failed, every product green. It was reporting the versions
installed on my own laptop, because that is where the table came from. It could not
have detected an update, ever.

UA publishes no versions anywhere public — not on their site, not in their release
notes, and their installer manifest is encrypted. So now those products say **"Firmware
Unknown"**, which is true, and link to UA's release notes so you can check by hand. A
permanent green tick is a lie that stops you looking.

The same rule runs throughout. Eventide's H90 page shows version 2.2.0 — that belongs
to a companion app, not the pedal, and the pedal's firmware is not published at all.
`devices_failed` (something broke) is kept separate from `devices_without_firmware`
(nothing to find), because conflating them either hides a real breakage or cries wolf
every single run.

## Being a good neighbour

Some of these sites are one-person operations. Sound-Force and TAL are not Google.

- **One request per second**, and a **daily** check rather than hourly — firmware ships
  a few times a year
- **Conditional requests** so unchanged pages come back as `304` with no body. Only 5 of
  23 vendors support it, but for those it saves the whole page every run
- **`SCRAPE_CACHE=1` while developing**, which serves repeat runs from disk. Debugging a
  scraper means fetching the same page dozens of times; measured at **35× faster** and,
  more to the point, 35× less traffic they have to carry

If you fork this, please keep those defaults. Every instance scrapes independently, so
N users is N times the load on the same small sites.

## Alternatives

Worth knowing what else exists before you invest time here.

**[FW//RADAR](https://fwradar.com)** is the closest thing, and if you only own hardware
it is probably the better choice — hosted, polished, with an iPhone app and used-market
prices that this has no answer to. It is closed-source, not self-hostable, and never
looks at what is installed on your machine.

**[daw-plugin-manager](https://github.com/thelukehendy/daw-plugin-manager)** overlaps on
plugins. It refreshes a curated version catalogue where this scrapes each vendor
directly: a catalogue is far less work to keep running, scraping cannot go stale because
nobody updated a file. Pick whichever failure mode you prefer.

**[pluginvault](https://github.com/GalAzu/pluginvault)** organises plugins rather than
versioning them. **[VST-Version-Scanner](https://github.com/BasShiFteR/VST-Version-Scanner)**
reports installed versions on Windows with nothing to compare them against.

Use this if you want the data on your own machine, want plugins and hardware in one
place, or want to add a vendor nobody else covers.

## Usage

**Add devices** from the catalogue at `/catalog`, or in bulk:

```bash
python scripts/scan_installed_plugins.py --compare   # what matches the database
python scripts/scan_installed_plugins.py --add       # import the matches
```

**Run a scrape** by hand:

```bash
curl -X POST http://localhost:8000/api/firmware/scrape-all
curl -X POST http://localhost:8000/api/firmware/scrape/strymon
```

It reports what it could not do, not just what it did:

```json
{
  "new_firmware_versions": 195,
  "devices_without_firmware": ["Hall of Fame 2"],
  "devices_failed": [],
  "devices_not_checked": []
}
```

**Backfill notifications** for a device whose installed version you recorded *after* its
latest was already known — a scrape only notifies about versions it discovers, so those
would otherwise never fire. Safe to re-run; one notification per device per version:

```bash
curl -X POST http://localhost:8000/api/firmware/reconcile-notifications
```

**Get them on your phone** by setting a transport:

```bash
NOTIFY_TRANSPORT=ntfy
NTFY_TOPIC=firmware-tracker-<long random string>
```

Delivery is a side effect: if ntfy is unreachable the notification is still recorded and
the failure logged. The test suite forces the transport off, so `pytest` on a configured
machine cannot push fixture alerts to your phone.

**Back up the database** with `bash scripts/backup_db.sh` (`list` and `restore` too).

## Security

**Authentication is off until you configure it**, which keeps a local install working
with no setup and is fine on localhost. Turn it on before this touches a public address:

```bash
python -m src.auth.hash_password
```

The app warns at startup while unconfigured, naming what is exposed — and it is
everything, including `POST /api/firmware/scrape-all` and full CRUD over your gear.
With auth on, only `/health`, `/login` and `/static` stay open: a load balancer cannot
present credentials, and requiring a session to reach the login form is a redirect loop.

Scripts can send `X-API-Key` instead, if `API_KEY` is set. Unset means the header is
ignored entirely, not that any key works. Passwords use scrypt, sessions use HMAC, both
from the standard library.

**On public ntfy.sh the topic name is the only secret.** Use a long random one
(`firmware-tracker-$(openssl rand -hex 16)`) and keep it in `.env`, which is gitignored.

## Health and logs

```bash
curl http://localhost:8000/health        # liveness  -> {"status":"ok","uptime_seconds":2.9}
curl http://localhost:8000/health/ready  # readiness -> {"status":"ok","database":"ok"}
```

`/health` touches nothing, so a failure means the process is wedged or gone. It
deliberately skips the database: if it checked, a slow disk would have the orchestrator
kill and replace tasks, which does not fix a slow disk. `/health/ready` runs a query and
returns **503** with a reason — on a deployment where the database is a file on a network
mount, losing that mount is exactly what this catches.

Logs go to stderr. Docker caps them at 10MB × 3; under systemd journald handles it; if
you run `uvicorn > file &` then nothing rotates it, so set `LOG_FILE` and the app rotates
for you. Access lines for `/health` are dropped by default — a container health check
polls it every 30 seconds, which is 95MB of log a year against about 1MB of actual
results.

## Configuration

Copy `.env.example` to `.env`. Everything has a working default; the ones you are most
likely to touch:

| Variable | Default | |
|---|---|---|
| `SCRAPE_INTERVAL_HOURS` | `24` | How often to check |
| `NOTIFY_TRANSPORT` | `none` | `ntfy` to push to your phone |
| `NTFY_TOPIC` | | Long and random — it is the only secret |
| `AUTH_PASSWORD_HASH` / `SECRET_KEY` | | Both required to enable auth |
| `ANTHROPIC_API_KEY` | | Enables changelog summaries |
| `SCRAPE_CACHE` | `false` | `true` while developing a scraper |
| `LOG_FILE` | | Set it if nothing else rotates your logs |

`.env.example` documents the rest, including cache TTLs, rate limiting and log levels.

## Supported manufacturers

| Hardware | Plugins |
|---|---|
| Boss | Eventide |
| Crumar | GForce Software |
| Elektron | IK Multimedia |
| Focusrite | iZotope |
| Line 6 | Modartt (Pianoteq) |
| Peterson | Moog |
| QSC | Native Instruments |
| Roland | Steinberg |
| Sound-Force | TAL Software |
| Strymon | Universal Audio |
| TC Electronic | |
| Tascam | |
| Yamaha | |

## Adding a scraper

Drop a file in `src/scrapers/plugins/`. It is auto-discovered on startup.

```python
from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult

class MyScraper(BaseScraper):
    manufacturer_name = "Acme Audio"
    manufacturer_slug = "acme"
    manufacturer_website = "https://acme.example.com"

    async def fetch_device_list(self) -> ScraperResult:
        ...

    async def fetch_firmware_versions(self, device_name, firmware_page_url) -> ScraperResult:
        ...
```

Return `success=False` when a fetch or parse breaks, and `success=True` with an empty
list when the page loaded and the product genuinely has none. Add the slug to
`tests/test_basic.py::test_api_scrapers`.

Two [Claude Code skills](.claude/skills/) live in this repo: one for writing a scraper,
one for debugging a broken one. The debugging ladder is worth reading first — the
failure is almost always a dead URL or a moved data source, not a parsing bug, and it
is written from the ones that actually broke.

## Development

```bash
pytest                                   # 159 tests
pytest --cov=src                         # 68% overall, 82% outside the scrapers
pytest tests/test_basic.py::test_dashboard
```

Tests use in-memory SQLite and never touch the real database.

CI gates coverage at two thresholds: **80% for application code**, and a looser 65% for
the whole project. Scrapers are verified against the live vendor site rather than by
coverage — Universal Audio was fabricating data at a healthy-looking 100%, so a passing
test proves much less there than a scrape does. The looser floor also leaves room for
new scrapers, which arrive with mostly-uncovered lines and cost about a point each.

One gotcha if you touch the coverage config: `concurrency = ["greenlet", "thread"]` is
load-bearing. SQLAlchemy bridges async to the sync DBAPI through greenlets, and without
it coverage stops tracing at each handler's first `await` into the database — which
understated the API and web layers by roughly 35 points and made them look untested.

<details>
<summary>Project layout</summary>

```
src/
  main.py              # FastAPI app, lifespan, router registration
  config.py            # Settings from .env
  database.py          # Async engine, session factory, integrity repair
  logging_config.py    # Handler, rotation, health-check access filter
  templating.py        # Jinja env with content-hashed asset URLs
  devices/             # Models, schemas, CRUD service, REST router
  web/                 # HTML page routes
  auth/                # scrypt hashing, HMAC sessions, middleware
  health/              # Liveness and readiness
  firmware/            # Scrape trigger endpoints
  scrapers/
    base.py            # aiohttp + Playwright helpers
    registry.py        # Auto-discovery via pkgutil
    service.py         # Orchestrates scrape -> sync -> notify
    cache.py           # Dev cache and ETag revalidation
    plugins/           # One file per manufacturer (23 scrapers)
  notifications/       # ntfy transport, and reconciliation
  scheduler/           # APScheduler periodic checks
  summarizer/          # Optional Claude changelog summaries
alembic/               # Migrations; env.py prefers DATABASE_URL
Dockerfile             # python:3.12-slim + Chromium, runs as uid 10001
docker-compose.yml     # Volumes, log caps
```
</details>

## Known limits

- The **plugin scanner is macOS only**. Windows plugins are DLLs with no `Info.plist`,
  so versions would need a completely different mechanism.
- Scrapers send a **browser User-Agent**, because some vendors reject anything else. The
  trade-off is that a vendor cannot tell who is calling or ask you to stop.
- The web app itself runs anywhere on Python 3.11+. Linux is CI-verified across 3.11,
  3.12 and 3.13; macOS is the development platform; Windows is untested.

## License

MIT
