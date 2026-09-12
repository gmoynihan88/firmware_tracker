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
   are not releases: prices, file sizes, sample library sizes and OS requirements all
   read as versions.

**Check whether one page covers the whole range before writing anything per-device.**
Line 6 lists every release it has ever shipped on `/software/Firmware`, and GForce
does the same on its Updates And Releases page — one fetch, cached on the scraper
instance, then look each device up. Both manufacturers complete in under 10 seconds
that way. Fetching a page per device that carries no version cost Focusrite 95s of
its 120s budget and made its last devices fail on timeouts.

**Discover product URLs from an index page rather than transcribing slugs.** Both
Focusrite and GForce had changed their URL shape — `/products/X` to `/product/x`,
title case to lowercase slugs — and every hardcoded URL 404'd. A discovered list
cannot rot the same way, and it picks up products added since.

**The best case is no `KNOWN_PRODUCTS` at all.** Arturia's two endpoints return the
product catalogue and every published download, so `fetch_device_list` and
`fetch_firmware_versions` both read from the same two responses: 183 products and
1,631 versions in 2.9 seconds, with no list in the source to go stale. Look for a
catalogue endpoint beside the one carrying versions — the downloads page had to get
its product filter from somewhere.

## Decide scope with the vendor's own taxonomy

A big catalogue is not automatically worth importing whole. Arturia publishes 782
products; 184 have a firmware line. The rest are 410 preset packs, 50 bundles and 427
in-app purchases, and `product_type` names all of them, so the filter is the vendor's
own classification rather than a guess about names.

The test is whether a row can ever report a version. Focusrite contributes 28 device
rows that will never say anything, because its firmware ships inside Focusrite
Control — 7% of the catalogue permanently reading "Firmware Unknown". Rows like that
make a catalogue worse, and the check is cheap to run before writing the scraper:
count how many of the products you plan to add appear in whatever source carries
versions.

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

### If a product reports nothing, say why

`success=True` with an empty list is honest but silent, and 95 products across the
catalogue are in that state. Set `firmware_availability` on the `ScrapedDevice` so the
absence is accounted for:

```python
ScrapedDevice(
    name=name,
    category="audio_interface",
    firmware_page_url=url,
    firmware_availability="not_published",   # or "no_firmware", or omit entirely
)
```

| Value | Use when | Example |
|---|---|---|
| `"not_published"` | The vendor publishes no version anywhere public | Focusrite, UADX plugins, Eventide pedals |
| `"no_firmware"` | The product takes no firmware updates at all | TC Electronic Hall of Fame 2 |
| omitted (`None`) | You have not established which | everything else |

**Omitting it is a real answer, and usually the right one.** Only set a value your
docstring can justify. TC Electronic marks Hall of Fame 2 and leaves Ditto X4,
Plethora X5 and the PolyTune 3s unmarked — they are probably the same story, and
probably is not what the field is for. A wrong value here is worse than no value,
because it stops anyone looking.

The point is the scrape summary. `devices_without_firmware` carries all 95 on every
run, which makes it wallpaper; `devices_unexplained` carries only the ones nothing
accounts for, and it is logged as a warning. A product that goes silent tomorrow shows
up in a list of a dozen rather than a list of ninety-five — but only if the expected
silences are marked.

A version always wins over the flag, so a vendor that starts publishing needs nothing
cleared.

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
4. Set `firmware_availability` on any product that reports no version, or decide
   deliberately to leave it unset.
5. Update the manufacturer table in `README.md`.

## Things this repo has already been bitten by

- **Do not add a hardcoded version table as a fallback.** It masks failures and goes
  stale while looking identical to scraped data. If you have no live source, name it
  `UNVERIFIED_*` and say so in the `changelog` field.
- **Product codes and URL shapes go stale.** Prefer identifiers you can re-derive from
  a catalogue endpoint over ones transcribed by hand.
- **Version strings vary in shape** — `Version 1.3.11`, `v5.1.3`, `v 1.9.8`. Normalise
  rather than assuming one form.
- **Product names differ from the database's.** Vendors write trademark symbols
  (`Oberheim OB-E®`), typographic characters (`Clarett⁺`), inconsistent casing
  (`3rd gen`), and they rename things (`Virtual String Machine` became `VSM IV`).
  Unnormalised, a scrape creates a second row and orphans the one the user's devices
  are attached to. Check `devices_synced` after the first run: a `created` count near
  the old device total means the names stopped matching.
- **Pair a version with its own date**, from the same changelog entry. Taking the first
  version and first date out of a shared block silently mismatches them.
- **Trust an API's data, not its self-description.** Arturia's resources endpoint has
  a `latest` flag that is per platform: KeyLab 88 has three records flagged latest,
  two of them two releases old. Derive the newest from the versions themselves —
  `ScraperService` already picks by version tuple, so return everything and let it
  choose. What an API *is* better at is telling one kind of thing from another: a
  `type` field separating firmware from editors and manuals replaces the most fragile
  part of an HTML scraper.
- **Check whether the vendor lists one product twice.** Arturia has two AudioFuse
  entries, different generations of the same interface, where the current one carries
  only the latest release and the retired one carries the history. Keyed by id that is
  two devices, one of them useless. Group the catalogue by display name and look at
  anything appearing more than once before choosing the key.
- **Most versions on a support page are not the product's.** Editor apps, USB drivers,
  transfer tools and manual revisions all carry version numbers and all sit on the
  page you are scraping. Roland lists `Driver Ver.1.0.3 for macOS Sonoma` beside
  `System Program (Ver.1.82)`; Eventide's H90 page leads with `Eventide Control 2.2.0`,
  which is an editor. Anchor on the wording that names the firmware itself.
- **Check your pattern against more than one page, in both directions.** A pattern
  looser than its parser drops data silently -- a date regex accepting `Sept` handed to
  `strptime` with `%b`, which only accepts `Sep`. A pattern stricter than the site
  returns nothing, which reads as "this product publishes no firmware" rather than as
  a bug.
- **Run `scripts/audit_scrapers.py` once the scraper is in.** It flags one version
  claimed across most of a catalogue, code nothing references, and fields you set that
  never reach the database. All three have caught scrapers that reported no failures.
