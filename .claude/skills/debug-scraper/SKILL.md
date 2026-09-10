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

Prefix manual runs with `NOTIFY_TRANSPORT=none` if a transport is configured.
Environment variables beat `.env`, and a scrape that finds versions for a tracked
device will deliver -- repeatedly, across a debugging session.

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
DEAD = ('404', 'not found', 'could not find', 'sorry', 'page unavailable')
async def main():
    s = CLASS()
    for url in ['URL_A', 'URL_B']:          # two different products, deliberately
        html = await asyncio.wait_for(s.fetch_page_js(url, wait_for_timeout=20000), timeout=90)
        t = s.parse_html(html).get_text() if html else ''
        head = t[:600].lower()
        print(f'{len(html or \"\"):>8} html {len(t):>6} text  dead={any(d in head for d in DEAD)}  {url[-40:]}')
    await s.close()
asyncio.run(main())
"
```

**Fetch two different products, and compare the text lengths.** Vendors serve dead
pages in ways that defeat a single check:

- **Line 6** returns HTTP 200 with "Sorry, we could not find that!" -- no "404", no
  "not found". Every `/support/page/kb/<product>/` URL was dead and all fifteen read
  as successful fetches of an empty page.
- **Focusrite** serves its 404 with the full site chrome: 3,385 characters of nav,
  search box and footer. A length threshold passes it.

What catches both is **two different URLs returning identical text length**. Three
Line 6 category pages all came back at exactly 1778 characters, which no real set of
product pages does.

Use the **full** URL from `KNOWN_PRODUCTS` — a truncated one 404s and sends you
chasing a phantom. Real cases: QSC had 8 products on `/support/software-firmware/`
which now 404s, and every TC Electronic `modelCode` was dead.

Also try `fetch_page` (aiohttp). Some vendors block it while allowing a real browser —
TAL and Modartt both do, which is why `fetch_page_js` exists.

### Always probe with a slug you know is fake

When guessing candidate URLs, include one that cannot exist. Some endpoints never
404: Moog's `softwareUpdate/<slug>` returns the same sixteen-line shell for every
slug, so a 200 proves nothing.

```
model-15          16285b  lines=16  versions=[]
minimoog-model-d  16325b  lines=16  versions=[]
moogerfooger      16305b  lines=16  versions=[]   <- invented, responds identically
mariana           20364b  lines=59  versions=['1.2.0', '1.1.0', '1.0.1']
```

Without the invented slug in that list, the honest reading is "those products publish
no firmware". With it, the reading is "this endpoint answers the same way for
anything, and only mariana has content" -- a different conclusion entirely.

This is the identical-length tell sharpened: comparing two real URLs catches a dead
path, comparing a real one against a fabricated one catches an endpoint that cannot
say no.

## Step 1b — Does one page carry every product?

Check before designing anything per-device. Several manufacturers publish a single
listing covering their whole range:

- Line 6: `/software/Firmware`, each entry naming the products it applies to.
- GForce: the Updates And Releases page, which also gives canonical product URLs.
- Focusrite: nothing per-device worth fetching at all.

Fetch it once and cache it on the scraper instance, then look each device up. Line 6
went from fifteen failures to seventeen successes in 9s this way; GForce does its
whole catalogue in 4s.

This is a correctness problem, not just speed. Fetching 28 Focusrite pages that carry
no version consumed 95s of the 120s per-manufacturer budget, and the last two devices
then failed on navigation timeouts -- which is indistinguishable from a broken page
until you time it. If a scraper is slow *and* its last few devices fail, suspect the
budget before the pages.

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

### Check for documentation hosted somewhere else

Vendors move release notes off their own domain, and the index page is where the
link lives. Sound-Force keeps SFC-8 and SFC-Mini V4 notes on
`soundforce.notion.site`, linked from its own support page.

Two things worth knowing before concluding data does not exist:

- **Notion renders fine** for a browser fetch, and in that case carried *better* data
  than the vendor's own pages: dated entries (`25/11/2025: V1.9:`) where the
  WordPress pages had none.
- **Zendesk does not.** Focusrite's and TC Electronic's support articles returned 403
  or a few hundred characters of shell every time, through every approach tried.

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

Units and money are the commonest false positives, because they are everywhere and
they look exactly right:

| Seen on the page | What it actually is |
|---|---|
| `149.99`, `1,139.00` | price |
| `16.55 MB` | file size |
| `3.5GB`, `12.5GB+` | sample library size |
| `macOS 10.13 or above` | OS requirement |
| `User Guide V4` | document revision |
| `2.0` in "Browser 2.0 implementation" | a feature named in the changelog prose |

A GForce product page yields four of these and no firmware version at all. If a
pattern matches something on a page you believe has no version, that is the pattern
being wrong, not the page being right.

Pair a version with its own date in one entry. TAL's old parser took the first version
and the first date from one block — different releases — recording 4.9.5 with 5.1.2's
date. `_parse_changelog` in `tal.py` shows the entry-at-a-time approach.

## Step 4b — Normalise product names before matching

Every scraper fixed recently needed this, and getting it wrong is silent: the scrape
creates a second row under the vendor's spelling and orphans the one your devices are
attached to.

| Vendor writes | Database has | Difference |
|---|---|---|
| `Oberheim OB-E®` | `Oberheim OB-E` | trademark symbol |
| `Clarett⁺ 2Pre` | `Clarett+ 2Pre` | superscript plus (U+207A) |
| `Scarlett 18i20 3rd gen` | `Scarlett 18i20 3rd Gen` | inconsistent casing |
| `VSM IV` | `Virtual String Machine` | renamed product |
| `Relay G10TII Transmitter` | `Relay G10II` | firmware ships under a component's name |

Compare the names the site gives against the rows already in the database before
writing the parser:

```bash
sqlite3 firmware_tracker.db "
SELECT dm.name FROM device_models dm
JOIN manufacturers m ON m.id=dm.manufacturer_id AND m.slug='SLUG' ORDER BY dm.name;"
```

Normalise punctuation and casing in code; keep genuine renames in an explicit alias
map so the intent is readable. Prefer discovering product URLs from an index page
over transcribing slugs -- Focusrite and GForce had both changed their URL shape, and
a discovered list cannot go stale the same way.

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
- **Run the suite and read the result before pushing, not alongside it.** Running
  pytest and pushing in one step means the failure and the push happen together, and
  CI reports it before you do.
- If a URL changed, note that `sync_devices` now refreshes `firmware_page_url` on
  existing rows, so the fix reaches devices already in the database.
- **Read `devices_synced` after the first real scrape.** `{'created': 16,
  'updated': 12}` means the existing twelve rows were refreshed and sixteen products
  are new. If `created` is close to the old device count, the names stopped matching
  and you have just duplicated the catalogue -- see Step 4b.
- Deleting a product from `KNOWN_PRODUCTS` leaves an orphan row in the DB that fails
  every scrape. Delete it explicitly, and check `my_devices` first.
