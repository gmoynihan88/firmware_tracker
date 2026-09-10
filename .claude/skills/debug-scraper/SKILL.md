---
name: debug-scraper
description: Diagnose and fix a manufacturer scraper that returns no firmware versions, fails to fetch, or reports data that does not match the vendor's site. Use when a scraper appears in devices_failed, returns empty results, or is suspected of serving stale or hardcoded versions.
---

# Debugging a scraper

Seven scrapers in this repo have been repaired with the ladder below. The failure is
almost always a **dead URL or a moved data source**, not a parsing bug — so resist
rewriting the parser until step 2 says the data is actually reachable.

## First: what does the scrape actually report?

```bash
.venv/bin/python -c "
import asyncio
from src.database import async_session_maker, init_db
from src.scrapers import service as ss
async def main():
    await init_db()
    async with async_session_maker() as db:
        r = await asyncio.wait_for(ss.scrape_manufacturer(db, 'SLUG'), timeout=300)
    for k, v in r.items(): print(f'{k}: {v}')
asyncio.run(main())
"
```

`devices_failed` means the fetch or parse broke. `devices_without_firmware` means the
scraper succeeded and the product genuinely has none — those are different, and the
distinction is load-bearing. Do not "fix" the second kind.

## Step 1 — Is the page a 404, or an empty JS shell?

Compare *rendered text* length, not HTML length. A live page runs to thousands of
characters; a stale URL or an unrendered SPA returns a few hundred.

```bash
.venv/bin/python -c "
import asyncio
from src.scrapers.plugins.MODULE import CLASS
async def main():
    s = CLASS()
    html = await asyncio.wait_for(s.fetch_page_js('URL', wait_for_timeout=20000), timeout=90)
    t = s.parse_html(html).get_text() if html else ''
    print('html bytes:', len(html or ''), '| text chars:', len(t))
    print('looks 404:', '404' in t[:400] or 'not found' in t[:500].lower())
    await s.close()
asyncio.run(main())
"
```

Use the **full** URL from `KNOWN_PRODUCTS` — a truncated one 404s and sends you
chasing a phantom. Real cases: QSC had 8 products on `/support/software-firmware/`
which now 404s, and every TC Electronic `modelCode` was dead.

Also try `fetch_page` (aiohttp). Some vendors block it while allowing a real browser —
TAL and Modartt both do, which is why `fetch_page_js` exists.

## Step 2 — If it renders in a browser but not for the scraper, find the real source

Capture the network. This is how the two hardest fixes were found.

```bash
.venv/bin/python -c "
import asyncio
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True)
        ctx = await b.new_context(user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        p = await ctx.new_page()
        calls = []
        p.on('request', lambda r: calls.append((r.method, r.url, r.post_data, dict(r.headers))))
        await p.goto('URL', wait_until='networkidle', timeout=60000)
        await p.wait_for_timeout(4000)
        for m, u, body, h in calls:
            if any(k in u.lower() for k in ('api','rest','json','download','firmware')):
                print(m, u[:140])
                if body: print('   body:', body[:200])
                for k in ('x-publishable-api-key','authorization','content-type'):
                    if k in h: print(f'   {k}: {h[k][:80]}')
        await b.close()
asyncio.run(main())
"
```

Watch for three things:

- **A JSON API.** Modartt's changelog page renders nothing server-side; the data comes
  from `POST /api/0/products` with body `{"action":"changelog","software":"pianoteq"}`.
  Without the body it returns `{"error":"Wrong parameters"}`.
- **A required header.** TC Electronic's store API needs
  `x-publishable-api-key: pk_…`, which is embedded in the page for client-side use.
  Plain requests return 400 without it.
- **Data embedded in the page.** See below.

## Step 3 — Next.js pages: join the RSC chunks before parsing

If the site is Next.js (`_next/static/chunks` in the requests), product data is often
streamed as escaped JSON inside `self.__next_f.push([1,"…"])` calls. **A single JSON
value can straddle two pushes**, so scanning the raw document finds arrays truncated
mid-string, with a `"]` that looks like a valid array close.

Symptom to recognise: the marker is present, but `json.loads` fails at a suspiciously
round offset, and **no amount of extra waiting helps**. It is not a timing problem —
five wait configurations were tested before this was understood.

`src/scrapers/plugins/tcelectronic.py` has the working implementation: `_rsc_payload`
decodes and concatenates every chunk, and `_match_bracket` ignores brackets inside
string literals.

## Step 4 — Parse structure, never free text

Scan the specific element that holds the version, not the page text. Free text
contains version-like strings that are not releases:

- Modartt: a changelog description mentioning macOS surfaced as version `10.3.9`.
  Fixed by reading only `div.mrt-title`.
- KVR: the only version left on an IK Multimedia page is `Version reviewed: 1.3.5`
  from a **user review**. A looser pattern reports a reviewer's version as the
  product's. That source was removed rather than made to match.

Pair a version with its own date in one entry. TAL's old parser took the first version
and the first date from one block — different releases — recording 4.9.5 with 5.1.2's
date. `_parse_changelog` in `tal.py` shows the entry-at-a-time approach.

## Step 5 — Never leave a hardcoded table as a silent fallback

A `KNOWN_FIRMWARE`-style table that fills in when scraping fails **masks the failure
and then rots**, while looking identical to real data in the UI.

What the audit found across six scrapers with hardcoded tables: **one fabricated**
(TC Electronic claimed Ditto+ 1.4 against a real 1.0.14), **one stale** (Modartt
claimed Pianoteq 9.2.4 against 9.2.5), two accurate but unchecked, one fine, one
genuinely unverifiable.

Choose deliberately:

- Source exists → scrape it, and **fail loudly** when the fetch breaks.
- Product is discontinued → a static value is honest; name it `SUPERSEDED_VERSIONS`.
- No public source at all → name it `UNVERIFIED_*` and say so in the `changelog`
  field, so it is distinguishable downstream. See `crumar.py`.

## Step 6 — Verify against the live site, and trust it over search

Run every product through the fixed scraper before believing it:

```bash
.venv/bin/python -c "
import asyncio
from src.scrapers.plugins.MODULE import CLASS
async def main():
    s = CLASS()
    for name, _c, url in s.KNOWN_PRODUCTS:
        r = await asyncio.wait_for(s.fetch_firmware_versions(name, url), timeout=90)
        print(f\"{'OK ' if r.success else 'FAIL'} {name:<20} {[f.version for f in r.firmware_versions][:4]}\")
    await s.close()
asyncio.run(main())
"
```

**Search results lag badly on version numbers.** A search said Kontakt was on 8.9.0;
NI's own thread said 8.13.0. Believing the search would have meant reporting a
correct scraper as broken. Always confirm on the vendor's page.

## Before opening a PR

- Tests offline against a fixture page — never the network. See
  `test_tal_pairs_each_version_with_its_own_date` for the pattern.
- If a URL changed, note that `sync_devices` now refreshes `firmware_page_url` on
  existing rows, so the fix reaches devices already in the database.
- Deleting a product from `KNOWN_PRODUCTS` leaves an orphan row in the DB that fails
  every scrape. Delete it explicitly, and check `my_devices` first.
