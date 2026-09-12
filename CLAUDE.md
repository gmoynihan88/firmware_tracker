# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Firmware Tracker is a FastAPI web app that scrapes manufacturer websites for firmware/software updates for music production hardware and VST plugins, stores them in SQLite, and notifies users when tracked devices have new versions. It uses a plugin-based scraper architecture with 24 manufacturer scrapers.

## Commands

Requires Python 3.11+.

```bash
# Install
pip install -e ".[dev]"

# Install with Playwright browser support (needed for JS-rendered scraper pages)
pip install -e ".[browser]" && playwright install chromium

# Run dev server (http://localhost:8000)
uvicorn src.main:app --reload

# Run all tests
pytest

# Run a single test
pytest tests/test_basic.py::test_dashboard

# Run tests with coverage
pytest --cov=src tests/

# Database migrations (note: alembic.ini uses sync sqlite:/// URL, not the async one from config)
alembic upgrade head
alembic revision --autogenerate -m "description"
```

## Architecture

**Layered structure:** Routers (API endpoints) → Services (business logic) → Models (SQLAlchemy ORM) → SQLite

**Key modules under `src/`:**
- `main.py` — FastAPI app, lifespan (init_db, scheduler start/stop), router registration
- `config.py` — Pydantic Settings loaded from `.env`
- `database.py` — Async SQLAlchemy engine + session factory (`get_db` dependency)
- `devices/` — Models, Pydantic schemas, CRUD service, REST router for Manufacturer, DeviceModel, MyDevice, FirmwareVersion, Notification
- `firmware/router.py` — API endpoints to list scrapers and trigger manual scrapes
- `web/router.py` — Jinja2 HTML page routes (dashboard, catalog, device detail, notifications)
- `scrapers/` — Plugin-based scraping system (see below)
- `scheduler/scheduler.py` — APScheduler runs `check_firmware_updates` every N hours and `generate_summaries` hourly
- `summarizer/service.py` — Anthropic Claude API for changelog summarization (optional, requires `ANTHROPIC_API_KEY`)

**Templates:** `templates/` (Jinja2) with `base.html` layout. **Static assets:** `static/css/`.

## Scraper Plugin System

Scrapers live in `src/scrapers/plugins/` and are auto-discovered by `ScraperRegistry` via `pkgutil`. Each scraper:
1. Subclasses `BaseScraper` from `src/scrapers/base.py`
2. Sets class attributes: `manufacturer_name`, `manufacturer_slug`, `manufacturer_website`
3. Implements `fetch_device_list()` → returns `ScraperResult` with `ScrapedDevice` list
4. Implements `fetch_firmware_versions(device_name, firmware_page_url)` → returns `ScraperResult` with `ScrapedFirmware` list

`BaseScraper` provides: `fetch_page()` (aiohttp), `fetch_page_js()` (Playwright for JS-rendered pages), `parse_html()` (BeautifulSoup/lxml), rate limiting, session management.

**Skills:** `.claude/skills/` carries two scraper skills — `add-scraper` for writing a
new plugin, and `debug-scraper` for diagnosing one that returns nothing or reports data
that does not match the vendor. The debugging ladder there is worth reading before
rewriting a parser: the failure is usually a dead URL or a moved data source.

**To add a new manufacturer scraper:** Create a new file in `src/scrapers/plugins/`, define a class inheriting `BaseScraper` with the required class attributes and abstract methods. It will be auto-registered. After adding a new scraper, add an assertion for its slug in `tests/test_basic.py::test_api_scrapers`.

**Registry caveat:** `ScraperRegistry` uses class-level state (`_scrapers`, `_initialized`). It persists across tests in the same process, which is fine for read-only checks but matters if a test modifies the registry.

**Scraping flow:** `ScraperService` in `src/scrapers/service.py` orchestrates: ensure manufacturer exists in DB → fetch device list → sync devices → for each device fetch firmware versions → sync firmware → create notifications for tracked devices.

## Database Models (src/devices/models.py)

Five tables: `Manufacturer` → `DeviceModel` → `FirmwareVersion`, `DeviceModel` → `MyDevice` (user-tracked instances), `MyDevice` + `FirmwareVersion` → `Notification`. Device categories: `GUITAR_PEDAL`, `AUDIO_INTERFACE`, `SYNTHESIZER`, `MIDI_CONTROLLER`, `VST_PLUGIN`, `OTHER`.

## API Routes

- `/api/manufacturers`, `/api/device-models`, `/api/my-devices` — RESTful CRUD
- `/api/firmware/scrapers` — List available scrapers
- `/api/firmware/scrape/{scraper_type}` — Trigger single manufacturer scrape
- `/api/firmware/scrape-all` — Trigger all scrapers
- `/` — Dashboard, `/catalog` — Browse devices, `/devices/{id}` — Device detail, `/notifications`

## Key Patterns

- **Fully async:** All database, HTTP, and I/O operations use async/await
- **Dependency injection:** FastAPI `Depends(get_db)` for database sessions
- **pytest-asyncio with `asyncio_mode = "auto"`:** Tests use async fixtures, DB is created/dropped per test
- **Playwright is optional:** Detected at import time via try/except; some scrapers need it for JS-rendered pages
- **AI summarization is optional:** Gracefully skipped if `ANTHROPIC_API_KEY` is not set
- **Tests use httpx `ASGITransport`:** The test client hits the FastAPI app in-process (no running server needed). The `setup_db` fixture creates/drops all tables per test.
