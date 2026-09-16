# Firmware Tracker

[![CI](https://github.com/gmoynihan88/firmware_tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/gmoynihan88/firmware_tracker/actions/workflows/ci.yml)

Keeps track of firmware and plugin versions for music gear — the hardware you own and the
software you have installed — and tells you when something is behind.

**[Browse the live catalogue →](https://firmware.gregmoynihan.dev/catalog)** · 2,045 devices across 91 vendors, no sign-in needed.

![The dashboard, filtered to devices with updates available](docs/images/dashboard.png)

*Filtered to devices with an update waiting. Sort any column; filter by status, brand or type.*

## Why

My QSC speaker had an update available that I overlooked for months, maybe a year or two,
called bass amp mode. HELL YEAH. This is one of my favorite software updates for anything,
ever, and I almost missed it.

Vendors rarely announce this stuff. There is no feed to subscribe to and no common release
channel — each manufacturer has its own downloads page, and checking them by hand does not
scale past a few devices. This scrapes 91 manufacturers on a schedule, compares what it
finds against the gear you own, and tells you when something is behind.

## Try it

```bash
git clone https://github.com/gmoynihan88/firmware_tracker.git
cd firmware_tracker
docker compose up
```

Open http://localhost:8000. Nothing to configure — it starts with no notifications, no AI
summaries and no authentication, which is fine on localhost.

The plugin scanner runs standalone, without the server or database. On macOS it reads the
VST3, VST, AU and CLAP folders and reports every plugin with its version and vendor:

```bash
python scripts/scan_installed_plugins.py
```

<details>
<summary>Without Docker</summary>

Requires Python 3.12+.

```bash
pip install --require-hashes -r requirements-dev.txt
playwright install chromium   # 10 scrapers need a browser
alembic upgrade head
uvicorn src.main:app --reload
```

Dependencies install from hashed lock files, so pip refuses any package whose contents
differ from the version that was reviewed. To change one, edit `pyproject.toml` and the
matching `.in` file, then re-run the `pip-compile` commands in `CLAUDE.md`.
</details>

## What it does

- **Scrapes 91 manufacturers** — synths, pedals, mixers, interfaces, DAWs and plugins
- **Tracks hardware and plugins together**, rather than one or the other
- **Scans installed plugins** on macOS and matches them to the catalogue
- **Checks daily** and pushes to [ntfy](https://ntfy.sh) when something falls behind
- **Optional AI changelog summaries** via the Anthropic API

## What's interesting about it

**It says "unknown" rather than guessing.** A scraper that invents a plausible version is
worse than one that reports nothing, and one here used to do exactly that — its hardcoded
table matched the plugins on my own laptop, so every product read as up to date by
construction. Absence is now a first-class result, with a reason attached where one is
known. [Design notes →](docs/design-notes.md)

**It runs on AWS for about $9 a month.** Terraform for everything, a single Fargate Spot
task behind CloudFront and an API Gateway VPC Link, SQLite on EFS, and deploys from GitHub
Actions using OIDC with no stored credentials. The largest line on the bill turned out to
be the public IPv4 address, not the compute. [Infrastructure →](infra/README.md)

**It tries not to be a nuisance.** One request per second per vendor, daily rather than
hourly, conditional requests, and the three vendors with no bulk listing check a slice of
their catalogue per run. [Scraping load →](docs/scraping-load.md)

**858 tests, 91% coverage**, two thresholds because scrapers are verified against live
vendor sites rather than by coverage. [Development →](docs/development.md)

## Usage

Add devices from the catalogue, or import what is already installed:

```bash
python scripts/scan_installed_plugins.py --compare   # what matches the database
python scripts/scan_installed_plugins.py --add       # import the matches
```

Trigger a scrape, and see what it could not do rather than only what it did:

```bash
curl -X POST http://localhost:8000/api/firmware/scrape-all
curl -X POST http://localhost:8000/api/firmware/scrape/strymon
```

Notifications go to your phone through ntfy:

```bash
NOTIFY_TRANSPORT=ntfy
NTFY_TOPIC=firmware-tracker-<long random string>
```

Backups, integrity checks, health endpoints, and a SQL recipe for finding versions a vendor
has quietly withdrawn: [Running it →](docs/operations.md)

## Configuration

Copy `.env.example` to `.env`. Everything has a working default; the ones you are most
likely to touch:

| Variable | Default | |
|---|---|---|
| `SCRAPE_INTERVAL_HOURS` | `24` | How often to check |
| `NOTIFY_TRANSPORT` | `none` | `ntfy` to push to your phone |
| `NTFY_TOPIC` | | Long and random — it is the only secret |
| `AUTH_PASSWORD_HASH` / `SECRET_KEY` | | Both required to enable auth |
| `PUBLIC_CATALOG` | `false` | `true` to let anyone read the catalogue |
| `ANTHROPIC_API_KEY` | | Enables changelog summaries |

`.env.example` documents the rest.

## Security

**Authentication is off until you configure it**, which keeps a local install working with
no setup. Turn it on before this touches a public address — the app warns at startup while
unconfigured, because without it every route is open, including `POST
/api/firmware/scrape-all` and full CRUD over your device list.

```bash
python -m src.auth.hash_password
```

`PUBLIC_CATALOG=true` opens the catalogue and the read-only device APIs to anyone, so the
app can be linked to as a demo — that is what the live site above runs. The dashboard,
notifications, tracked devices and every write stay behind the password, and an anonymous
visitor sees no tracking markers, because which products someone owns is not part of the
catalogue.

Five failed logins from one address in five minutes make `/login` answer 429. Passwords use
scrypt, sessions use HMAC, both from the standard library. Behind a proxy that terminates
TLS, set `SESSION_COOKIE_SECURE=true` and run uvicorn with `--proxy-headers`.

## Alternatives

**[FW//RADAR](https://fwradar.com)** covers the same ground as a hosted service and is the
better option for hardware-only users: polished, with an iPhone app and used-market prices.
It is closed-source, not self-hostable, and does not read what is installed on your machine.

**[daw-plugin-manager](https://github.com/thelukehendy/daw-plugin-manager)** overlaps on
plugins, refreshing a curated catalogue where this scrapes each vendor directly. A catalogue
is less work to maintain but depends on someone updating it; scraping breaks when a site
changes but cannot silently fall behind.
**[pluginvault](https://github.com/GalAzu/pluginvault)** organises plugins rather than
versioning them. **[VST-Version-Scanner](https://github.com/BasShiFteR/VST-Version-Scanner)**
reports installed versions on Windows with nothing to compare them against.

This one is useful if you want the data self-hosted, want hardware and plugins tracked
together, or need a vendor the others do not cover.

## Supported manufacturers

<details>
<summary>91 vendors — 2,045 devices</summary>

| Hardware | Plugins |
|---|---|
| 1010music | Ableton (Live) |
| Akai Professional | Apple (Logic Pro, MainStage) |
| Allen & Heath | Avid (Pro Tools) |
| Arturia\* | Bitwig (Studio) |
| ASM | Cableguys |
| Audient | Cockos (REAPER) |
| Boss | FabFilter |
| Casio | GForce Software |
| Conductive Labs | Goodhertz |
| Crumar | IK Multimedia |
| DiGiCo | Image-Line (FL Studio) |
| Dirtywave | iZotope |
| Dreadbox | Kilohearts |
| Elektron | Klanghelm |
| Empress Effects | Modartt (Pianoteq) |
| Engine DJ (Denon DJ, Numark, Rane) | Moog |
| Eventide\* | MOTU (Digital Performer) |
| Fender | Native Instruments |
| Focusrite | OBS Project (OBS Studio) |
| Fractal Audio | oeksound |
| HeadRush | PreSonus (Fender Studio, Notion) |
| Hotone | PSPaudioware |
| iConnectivity | Serato |
| Keith McMillen | Soundtoys |
| Kemper | Steinberg |
| Korg | TAL Software |
| Line 6 | Tokyo Dawn Labs |
| Mooer | Toontrack |
| Neural DSP | u-he |
| Nord | Universal Audio |
| Novation | Valhalla DSP |
| Oberheim | Waves |
| OXI Instruments | Xfer Records |
| Peterson | XLN Audio |
| Pioneer DJ |  |
| Polyend |  |
| Positive Grid\* |  |
| QSC |  |
| RME |  |
| Roland |  |
| Roland Pro AV |  |
| Sequential |  |
| Sequentix |  |
| Solid State Logic |  |
| Sound-Force |  |
| Soundcraft |  |
| Squarp Instruments |  |
| Strymon |  |
| Synthstrom Audible |  |
| Tascam |  |
| TC Electronic |  |
| Teenage Engineering |  |
| Torso Electronics |  |
| Waldorf |  |
| Yamaha |  |
| Yamaha Pro Audio |  |
| Zoom |  |

\*Arturia, Eventide and Positive Grid are on both sides: Arturia 116 instruments and
effects alongside 67 hardware products, Eventide 54 plugins and 29 pedals, Positive Grid 6
BIAS plugins and 11 Spark and BIAS amps and controllers.
</details>

## Adding a scraper

Drop a file in `src/scrapers/plugins/` subclassing `BaseScraper`; it is auto-discovered on
startup. The shape, the conventions and the debugging ladder are in
[docs/development.md](docs/development.md).

## Known limits

- The **plugin scanner is macOS only**. Windows plugins are DLLs with no `Info.plist`, so
  versions would need a completely different mechanism.
- Scrapers send a **browser User-Agent**, because some vendors reject anything else. The
  trade-off is that a vendor cannot tell who is calling or ask you to stop.
- **Release dates are missing for a quarter of current versions** — 1,375 of 1,923 have
  one. That is what the vendor publishes, not what the scraper managed to read.
- The web app runs anywhere on Python 3.12+. Linux is CI-verified on 3.12 and 3.13, macOS
  is the development platform, Windows is untested.

<details>
<summary>Project layout</summary>

```
src/
  main.py              # FastAPI app, lifespan, router registration
  config.py            # Settings from .env
  database.py          # Async engine, session factory, integrity repair
  templating.py        # Jinja env with content-hashed asset URLs
  devices/             # Models, schemas, CRUD service, REST router
  web/                 # HTML page routes
  auth/                # scrypt hashing, HMAC sessions, middleware, login throttle
  health/              # Liveness and readiness
  firmware/            # Scrape trigger endpoints
  scrapers/
    base.py            # aiohttp + Playwright helpers
    registry.py        # Auto-discovery via pkgutil
    service.py         # Orchestrates scrape -> sync -> notify
    notes.py           # Release notes as lines, shared by several scrapers
    plugins/           # One file per manufacturer (91 scrapers)
  notifications/       # ntfy transport, and reconciliation
  scheduler/           # APScheduler periodic checks
  summarizer/          # Optional Claude changelog summaries
alembic/               # Migrations; env.py prefers DATABASE_URL
infra/                 # Terraform: VPC, ECS, EFS, API Gateway, CloudFront, budgets
Dockerfile             # python:3.12-slim + Chromium, runs as uid 10001
```
</details>

## License

MIT
