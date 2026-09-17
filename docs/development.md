# Development

```bash
pytest                                   # 875 tests
pytest -n auto                           # the same in parallel, one worker per CPU, as CI runs
pytest --cov=src                         # 91% overall, 90% outside the scrapers
pytest tests/test_basic.py::test_dashboard

coverage report --omit='src/scrapers/plugins/*' --fail-under=80   # the gates CI runs
coverage report --fail-under=65
```

Tests use in-memory SQLite and never touch the real database.

## Two coverage thresholds

CI enforces 80% for application code and 65% for the whole project. The second is
deliberately looser: scrapers are verified against the live vendor site rather than by
coverage, and each new one arrives with mostly-uncovered lines, costing roughly a point of
the total. A high number there would mean tests written to satisfy a gate.

`concurrency = ["greenlet", "thread"]` in `pyproject.toml` is required for those numbers to
be accurate. SQLAlchemy bridges async to the sync DBAPI through greenlets, and without it
coverage stops tracing at each handler's first `await` into the database, which understated
the API and web layers by roughly 35 points.

## The suite does not depend on your machine

`tests/conftest.py` forces `NOTIFY_TRANSPORT`, `AUTH_PASSWORD_HASH`, `SECRET_KEY`,
`API_KEY` and `PUBLIC_CATALOG` to safe values before `src.config` is imported. Environment
variables beat the `.env` file, which is what makes this work — and it is not theoretical:
generating the deployment's real auth values put them in `.env`, after which 59 tests
failed on 401s that had nothing to do with the code under test. CI never saw it, having no
`.env`.

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

Return `success=False` when a fetch or parse breaks, and `success=True` with an empty list
when the page loaded and the product genuinely has none. Add the slug to
`tests/test_basic.py::test_api_scrapers`, and run
`python scripts/update_readme_counts.py` so the README counts stay in step.

The repo carries [Claude Code skills](../.claude/skills/) for writing a scraper, debugging
one, and working through a batch of vendors. The diagnostic ladder is drawn from the
scrapers that actually broke here; in nearly every case the cause was a dead URL or a
relocated data source rather than a parsing error.

Two scripts are worth knowing:

```bash
python scripts/audit_scrapers.py     # scrapers that are wrong while reporting success
python scripts/sweep_scrapers.py     # every scraper, live, uncached -- about 25 minutes
```

`audit_scrapers.py` catches one version claimed across most of a vendor's catalogue, code
nothing references, and fields set that never reach the database. All three have found
scrapers that reported no failures.
