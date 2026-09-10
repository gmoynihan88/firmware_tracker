---
name: add-scraper
description: Add a new manufacturer scraper plugin to src/scrapers/plugins/. Use when adding support for a manufacturer the tracker does not yet cover, or when scaffolding a scraper class that follows this repo's conventions.
---

# Adding a manufacturer scraper

Scrapers live in `src/scrapers/plugins/` and are auto-discovered by `ScraperRegistry`
via `pkgutil` — there is no registration step. Subclass `BaseScraper`, set three class
attributes, implement two methods.

## Find the data source before writing any code

The most common mistake is scraping HTML when the vendor serves JSON. Load a product
page with Playwright and watch the network first — the procedure is in the
`debug-scraper` skill, step 2. Several manufacturers here turned out to have a real
API behind a page that renders nothing server-side.

Preference order:

1. A JSON API the site itself calls (Modartt, TC Electronic).
2. Structured data embedded in the page (Next.js RSC payloads).
3. A stable text pattern in specific markup (TAL's `Version 5.1.2 / 03.11.2025`,
   QSC's `Firmware version for all models: version 2.1.43`).
4. Free-text scanning — last resort, and prone to matching version-like strings that
   are not releases.

## Skeleton

```python
import re
from typing import List, Optional

from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult


class AcmeScraper(BaseScraper):
    """Scraper for Acme Audio hardware."""

    manufacturer_name = "Acme Audio"
    manufacturer_slug = "acme"          # registry key; keep it lowercase and stable
    manufacturer_website = "https://acme.example.com"

    # (name, category, firmware_page_url)
    KNOWN_PRODUCTS = [
        ("Model One", "guitar_pedal", "https://acme.example.com/products/model-one"),
    ]

    async def fetch_device_list(self) -> ScraperResult:
        return ScraperResult(
            success=True,
            devices=[
                ScrapedDevice(
                    name=name,
                    category=category,
                    firmware_page_url=url,
                    product_url=url,
                )
                for name, category, url in self.KNOWN_PRODUCTS
            ],
        )

    async def fetch_firmware_versions(
        self, device_name: str, firmware_page_url: str
    ) -> ScraperResult:
        html = await self.fetch_page_js(firmware_page_url, wait_for_timeout=20000)
        if not html:
            return ScraperResult(success=False, error=f"Failed to fetch {firmware_page_url}")

        versions = self._parse(html)
        if not versions and not self._page_rendered(html):
            return ScraperResult(
                success=False,
                error=f"No firmware data for {device_name} at {firmware_page_url}",
            )

        # Empty here is a real answer: some products ship no firmware at all.
        return ScraperResult(success=True, firmware_versions=versions)
```

Categories map to `DeviceCategory` in `src/devices/models.py`: `guitar_pedal`,
`audio_interface`, `synthesizer`, `midi_controller`, `vst_plugin`, `other`.

## The success/failure distinction matters

This is the single most important convention here, because getting it wrong is how
this codebase hid broken scrapers for months.

- **`success=False`** — the fetch or parse broke. Lands in `devices_failed`.
- **`success=True` with an empty list** — the page loaded and the product genuinely
  has no firmware. Lands in `devices_without_firmware`.

Both are legitimate. TC Electronic's Hall of Fame 2 is TonePrint-only and ships no
firmware; reporting that as a failure would be a permanent false alarm. Conversely, an
empty success on a page that never loaded hides a dead URL.

When you cannot distinguish them from the result alone, test whether the page actually
rendered — presence of the expected data structure is a better signal than text length.

## Helpers on BaseScraper

- `fetch_page(url)` — aiohttp. Some vendors block it; check before relying on it.
- `fetch_page_js(url, wait_for_timeout=…)` — Playwright, for JS-rendered pages.
  Optional dependency, guarded by `PLAYWRIGHT_AVAILABLE`, so never import Playwright
  at module scope in a plugin.
- `parse_html(html)` — BeautifulSoup with lxml.
- `_rate_limit()` / `_get_session()` — call these if you fetch outside the helpers.

## Wire-up checklist

1. Add the slug assertion in `tests/test_basic.py::test_api_scrapers`.
2. Add offline parser tests against a fixture string — never hit the network in tests.
   `test_tal_pairs_each_version_with_its_own_date` is a good model.
3. Run every product through the scraper live before opening a PR (command in the
   `debug-scraper` skill, step 6).
4. Update the manufacturer table in `README.md`.

## Things this repo has already been bitten by

- **Do not add a hardcoded version table as a fallback.** It masks failures and goes
  stale while looking identical to scraped data. If you have no live source, name it
  `UNVERIFIED_*` and say so in the `changelog` field.
- **Product codes and URL shapes go stale.** Prefer identifiers you can re-derive from
  a catalogue endpoint over ones transcribed by hand.
- **Version strings vary in shape** — `Version 1.3.11`, `v5.1.3`, `v 1.9.8`. Normalise
  rather than assuming one form.
- **Pair a version with its own date**, from the same changelog entry. Taking the first
  version and first date out of a shared block silently mismatches them.
