---
name: debug-scraper
description: Diagnose and fix a manufacturer scraper that returns no firmware versions, fails to fetch, or reports data that does not match the vendor's site. Use when a scraper appears in devices_failed, returns empty results, or is suspected of serving stale or hardcoded versions.
---

# Debugging a scraper

Two rounds of repairs across this repo's scrapers produced the ladder below — the
first for scrapers returning nothing, the second for scrapers returning versions
without dates. The failure is almost always a **dead URL or a moved data source**,
not a parsing bug, so resist rewriting the parser until step 2 says the data is
actually reachable.

## Start here

| Symptom | Go to |
|---|---|
| Don't know which scraper is wrong | Step 0 — they report success |
| `devices_failed` has entries | Step 1 — dead URL or JS shell |
| Every product returns nothing | Step 1, then 1b |
| Scraper is slow *and* its last products fail | Step 1b — budget, not pages |
| Renders in a browser, empty for the scraper | Step 2 — find the real source |
| Versions found, but they are the wrong thing | Step 4 — editors, drivers, manuals |
| Versions right, dates missing or wrong | Step 4, then the dates section |
| One version repeated across the catalogue | Step 0's audit, then Step 6 |
| Data comes from an API and still looks wrong | Step 2b — API metadata lies too |
| "Firmware only ships through the vendor's app" | Step 4c — that predicts nothing; watch what the app fetches |
| Scrape creates new rows instead of updating | Step 4b — name normalisation |

## Step 0 — Which scraper is lying?

The ladder below assumes you know which scraper is broken. Usually you do not, because
the broken ones report success. Elektron gave eleven products the same two versions,
read off a news blurb on a page that ignored its own query parameter, with
`devices_failed` empty the whole time. Universal Audio ran in 0.01s, everything green,
reporting the versions installed on this laptop.

```bash
.venv/bin/python scripts/audit_scrapers.py
```

Three checks, no network:

- **One version across most of a vendor's catalogue.** Eleven Elektron products
  sharing two versions is impossible; MC-101, MC-707 and VERSELAB MV-1 sharing Roland
  System Program 1.82 is a real platform release. The output is a question.
- **Defined and never referenced.** QSC's `_parse_k2_firmware_page` read the release
  date correctly and was called from nowhere, so the date reached the database once
  and could not be produced again.
- **Sets a field the database never receives.** Boss carries a careful two-format date
  extractor for a page layout that no longer exists. The code runs and the pattern
  never matches, which no static check can see.

**A sweep that finds nothing and a sweep that is broken look identical.** Point it at a
commit from before a known fix before believing a clean report -- run against the
commit preceding QSC's removal, it prints exactly that one orphaned method.

### The fourth check runs during a scrape

A dead URL cannot be found without fetching, so that one lives in `BaseScraper`.
Every page fetched is fingerprinted, and `scrape_manufacturer` warns when several
*different* URLs returned the same thing:

    Yamaha: 11 different URLs returned identical content, so the URL shape may no
    longer select a product -- .../modx6_firm.html, .../modx7_firm.html, ...

It reads the visible text with scripts stripped, not the raw body. Elektron's pages
are identical in every way that matters and differ by one injected value,
`window.__wc_fb_page_generated = 1789238504`, which changes per request and is the
same length every time -- hashing the body makes eleven copies of one page look like
eleven distinct ones, which is the exact case the check exists for. That was found by
validating the check against the pre-fix URL shape and watching it report nothing.

Products sharing a single URL -- QSC's K.2 range, all of Peterson, all of Steinberg --
are one URL rather than several and do not appear.

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

**Add `SCRAPE_CACHE=1` once you have the page in hand.** Debugging means running the
same fetch dozens of times against data that has not changed, and the vendors carry
all of it. The cache stores bodies under `.scrape_cache/` for six hours, keyed on the
full request, and a hit returns before Playwright launches -- a four-product Steinberg
run goes 2.25s to 0.00s. Turn it *off* to confirm a fix against the live site, since
a cached run cannot discover a new version. Delete `.scrape_cache/` to force a refetch
without changing the flag.

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

### Always probe with a slug that cannot possibly be a product

When guessing candidate URLs, include a control: a slug you are certain does not
exist. Some endpoints never 404. Moog's `softwareUpdate/<slug>` returns the same
sixteen-line shell for anything, so a 200 there proves nothing.

```
mariana                   20364b  lines=59   <- real content
moogerfooger              16305b  lines=16
spectravox                16295b  lines=16
messenger                 16290b  lines=16
zzqx-not-a-product-9f3a   16360b  lines=16   <- control, responds identically
definitely-fake-slug-xyz  16365b  lines=16   <- control, responds identically
```

Without a control the honest reading is "those products publish no firmware". With
one it is "this endpoint answers the same way for anything, and only mariana has
content" -- a different conclusion, reached from the same responses.

**Make the control obviously impossible, like a random string.** The first attempt at
this used `moogerfooger`, `spectravox` and `messenger` as the fakes. All three are
real Moog products. A plausible-sounding name you have not heard of is a name you
have not heard of, not a name that does not exist, and a control chosen that way
tests nothing. The conclusion happened to survive; the evidence for it did not.

This is the identical-length tell sharpened: comparing two real URLs catches a dead
path, comparing a real one against a fabricated one catches an endpoint that cannot
say no.

**Sometimes no rule separates the control from a live page, and that is the answer.**
A fabricated slug under Yamaha's `/products/.../<slug>/downloads.html` returns the
*category index* with a 200 and a perfectly ordinary title. Titles do not tell them
apart: the live pages are "reface - Downloads - Synthesizers" and "MONTAGE M
Synthesizer Manuals & Software", so requiring the word Downloads rejects the second
one. That was written, tested against the products, and reverted.

When the page itself cannot be identified as dead, make the *parser* the thing that
refuses: the category index carries no updater row, so a scraper that only reads
rows reports nothing for it. This works only if there is no free-text fallback
underneath -- one scanning for anything shaped like a version will happily find
something on a category page. See Step 5.

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

## Step 2b — An API is cleaner, not truer

Finding the JSON is the win. Believing its own summary of itself is the next mistake,
and it is easier to make than the HTML equivalent because the field is *named* for
what you want.

Arturia's `/api/content/resources` returns every downloadable it publishes, with a
`latest` boolean. The flag is per platform, not per product:

```
KeyLab 88   latest=true   v1.2.0.6   platform=""
KeyLab 88   latest=true   v1.1.0.4   platform="mac"
KeyLab 88   latest=true   v1.1.0.4   platform="windows"
```

Three records flagged latest, and two are two releases behind. A scraper reading
`latest` reports 1.1.0.4 forever, with an API to point at as justification. Derive
the newest yourself — `ScraperService` picks by version tuple, so returning every
version and letting it choose is both simpler and right.

**What an API is genuinely better at is telling one kind of thing from another.** The
hardest HTML problem in this repo is that editors, drivers and manuals carry versions
and sit on the product's page. Arturia's records have a `type`: 270 `firmware`, 4,103
`soft`, 1,557 `manual`. The MiniFreak instrument is 4.0.1 and the MiniFreak V editor
is 4.0.2.6369, and no wording has to be anchored on to separate them. When an endpoint
offers a discriminator, it replaces the most fragile part of a scraper.

### One product can appear twice

Not the [name-normalisation problem](#step-4b--normalise-product-names-before-matching),
which is the vendor's spelling against yours. This is the vendor's catalogue against
itself: two entries, the same name, the same device.

Arturia lists AudioFuse twice, generations 0 and 2 — same firmware, same versions,
except the current entry carries only the latest release and the retired one carries
the history. Keyed by id you get two devices, one with no history and one nobody
looks at. Keyed by name, with their resources merged, you get one device with all
four versions.

Check for it before designing the key: group the catalogue by display name and look
at anything appearing more than once.

### One release can have two dates

Platform builds finish on different days: 51 of Arturia's 2,055 software versions are
dated a day apart on mac and windows. Take the earliest — the release is when it first
shipped, not when the last build came out of CI. Either choice is defensible; an
unconsidered one means the date changes depending on which record the parser happened
to see last.

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

### A flattened table puts every value against the wrong row

Worse than noise, because it is consistent and therefore convincing. Yamaha's
downloads pages are a table:

| Name | OS | Size | Last Update |
|---|---|---|---|
| MONTAGE M OS Updater V3.01 from version V3.00 | - | 75.4MB | 2026-01-14 |
| Yamaha Steinberg USB Driver V2.1.9 for Windows | Win | 8.2MB | 2025-06-25 |

`get_text()` renders that as:

```
...Updater V3.01 from version V3.00 - 75.4MB 2026-01-14 Yamaha Steinberg USB Driver V2.1.9...
```

Each date now sits immediately before the **next** row's name. Read as text, every
date on the page looks like it introduces the entry below it, so the page reads as
though only the drivers are dated and the updaters are not. That conclusion was
written into the scraper's docstring -- "No dates, checked rather than assumed" --
and stood for as long as nobody looked at the cells.

The tell is a date that makes no sense for the thing it appears to modify, or a
column of dates that all seem to belong to entries of one kind. Iterate `tr`, index
the cells by their header, and the ambiguity disappears.

### The version on the page often belongs to something else

This is the commonest way a scraper reports a real number for the wrong thing. The
page is about the product; the version is not.

| Page says | Belongs to |
|---|---|
| Eventide H90: `Eventide Control 2.2.0`, `H90 Control 1.9.15` | editor apps, not the pedal -- whose own notes read "Requires H90 firmware 1.9.4+" |
| Roland MC-101: `Driver Ver.1.0.3 for macOS Sonoma` | a USB driver, beside `System Program (Ver.1.82)` |
| Elektron Digitakt: `Elektron Transfer 1.10.4` | a desktop transfer tool |
| QSC TouchMix: `Revised 06/07/2017` | the installation instructions, not the firmware |
| Eventide: `Version 9 \| English` | a manual revision |

Two signals separate them. The firmware entry usually names the thing -- "System
Program", "OS", "Installer" -- and the companion entry names a different product. And
the companion's numbering runs on its own track: H90 Control was on 1.9.15 while H90
firmware was on 1.9.4.

### Calibrate the pattern against the page, in both directions

Two failures, both made in the same afternoon, opposite to each other and each
invisible without checking.

**Looser than its parser.** Elektron writes `Sep 9, 2026` on some pages and
`Sept 9, 2026` on others. A regex matching `(Jan|...|Sep)[a-z]*` accepts both, then
`strptime` with `%b` rejects the four-letter form. Every MKII page silently came back
undated while the code looked like it handled them.

**Stricter than reality.** Roland writes `System Program (Ver.1.82)` and also
`J-6 System Program Ver.1.02`. Requiring the parentheses returned nothing for the AIRA
Compacts -- and "no versions found" reads exactly like "this product has none".

When a product returns nothing, check the page before accepting it. A zero is a claim.

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
map so the intent is readable.

**If an identity can come from more than one place, normalise every route to one
key.** The plugin scanner derives a vendor from the bundle id when it is reverse-DNS
and from the copyright string otherwise. Fixing it to use both produced
`native-instruments` from one route and `Native Instruments` from the other -- one
vendor counted as two, which is the bug it was meant to fix wearing a different hat.
Slugifying both outputs fixed it. Whenever you add a fallback source for a name,
check the two agree on a single value before trusting either.

Prefer discovering product URLs from an index page over transcribing slugs --
Focusrite and GForce had both changed their URL shape, and a discovered list cannot
go stale the same way.

## Step 4c — How firmware is delivered says nothing about whether it is published

The most expensive wrong inference made in this repo, and it reads as obvious sense:
this vendor ships firmware through its own installer, so there is no version to
scrape. It cost 22 products with dated history.

Universal Audio's UADX plugins go through UA Connect, and the manifest it fetches is
an encrypted blob — genuinely unscrapeable. The whole vendor was written off on that
basis. But UA's UAFX pedals go through UA Connect too, and their release notes open
with:

> To update your pedal's firmware, use UA Connect.

and then list sixteen versions with dates back to March 2021. Same installer, same
vendor, fully published.

The same split runs through Eventide: pedal firmware ships via Eventide Device
Manager and is published nowhere, while the plug-ins on the same downloads page carry
versions. And Yamaha's updaters are downloaded manually, which implies nothing either
way — what mattered was a table nobody had read.

**Delivery mechanism and publication are independent.** The only thing that settles it
is looking for the release notes — or, better, at what the vendor's own updater asks
for.

### Open the companion app's web version and watch its network

The updater has to learn the current version from somewhere. If it has a web build,
that request is visible, and it is the vendor's own source rather than a page written
about it.

Novation is the clean case. Its downloads site is a convincing dead end: every
product page leads with `Novation USB Driver 2.30.0.83` — one driver, the same
version everywhere — then DAW scripts, then a link reading "Go to Components Web".
Peak and Summit list nothing but drivers. Loading `components.novationmusic.com` and
watching the network shows:

```
GET https://components.novationmusic.com/api/v2/firmwares
```

No key required, 118 records over 24 products, and Peak and Summit are both on 2.2 —
versions their own product pages do not admit exist.

Universal Audio is the same move with the opposite answer: UA Connect fetches
`external-content.db` from S3 and it is an encrypted blob. That is still worth
knowing, because it turns "we could not find it" into "it is not obtainable".

Try, in order: the app's web build, the vendor's support site (a Zendesk Help Center
answers `/api/v2/help_center/articles/search.json?query=firmware+release+notes` where
the HTML does not), and only then conclude nothing is published.

### One API can version several components under one product

Novation's manifest carries `firmware_type`, and six of its records are `fpga` rather
than `firmware`. Their version numbers **collide exactly** with the instrument's:
Peak has an fpga 2.1 and a firmware 2.1, Summit likewise. Deduplicating by version
string silently keeps whichever came last, so "Peak 2.1" ends up pointing at the FPGA
image.

This is the "belongs to something else" trap at its least visible — not an editor
with its own numbering on a shared page, but the same product, the same version
string, a different component, inside one authoritative endpoint. Check whether a
type discriminator exists before grouping by version, and filter on it.

Other places to look for the notes:

- The vendor's own support site, especially a Zendesk Help Center — `/api/v2/help_center/articles/search.json?query=firmware+release+notes` answers where the HTML does not.
- Search the help centre per product line rather than per product. UA has one article
  for all 21 UAFX pedals, the way Roland has one System Program per family.
- A vendor with nothing for one product line may publish fully for another, so
  conclude per line, not per vendor.

When a vendor genuinely publishes nothing, record that with `firmware_availability`
rather than leaving it as an unexplained silence — see the `add-scraper` skill.

## Step 5 — Never leave a hardcoded table as a silent fallback

A `KNOWN_FIRMWARE`-style table that fills in when scraping fails **masks the failure
and then rots**, while looking identical to real data in the UI.

What the audit found across six scrapers with hardcoded tables: **one fabricated**
(TC Electronic claimed Ditto+ 1.4 against a real 1.0.14), **one stale** (Modartt
claimed Pianoteq 9.2.4 against 9.2.5), two accurate but unchecked, one fine, one
genuinely unverifiable.

### The worst case is a table copied from your own machine

Universal Audio's `KNOWN_FIRMWARE` held ten versions that matched the plugins
installed on this laptop **exactly**, because that is where they came from. So it
reported every UA plugin as up to date by construction, could never report anything
else, and paired each version with an invented release date. It looked like the
healthiest scraper in the repo: 0.01s, no failures, everything green.

The tell is a scraper that never fetches and whose versions equal what
`scripts/scan_installed_plugins.py` finds. Check that before trusting a table:

```bash
sqlite3 firmware_tracker.db "SELECT dm.name, fv.version FROM firmware_versions fv
JOIN device_models dm ON dm.id=fv.device_model_id
JOIN manufacturers m ON m.id=dm.manufacturer_id AND m.slug='SLUG' WHERE fv.is_latest=1;"
# then compare against the installed bundle versions
```

If a vendor genuinely publishes nothing, **report no version** rather than the
installed one. `devices_without_firmware` renders as "Firmware Unknown", which is
true and prompts a manual check; a permanent green tick is false and prevents one.
Keep the product rows and point `firmware_page_url` at the closest human-readable
page. See `universal_audio.py`, whose docstring records every source ruled out so the
search is not repeated.

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

### `.env` sets `SCRAPE_CACHE=true`, so "live" runs are not live

This step is the one the cache silently defeats. The repo's `.env` turns the dev
cache on, `get_settings()` reads it, and a verification run then confirms the parser
against HTML saved earlier rather than against the vendor. Nothing says so: every
scraper reports `ok`, every device count is right, and the result is worthless as
evidence the site still exists.

Pass it explicitly on the command line, which overrides `.env`, and print what took
effect so the output cannot be misread later:

```bash
SCRAPE_CACHE=false .venv/bin/python -c "
from src.config import get_settings
print('scrape_cache:', get_settings().scrape_cache)
..."
```

**The tell is implausible timing.** A full sweep that reported every scraper healthy
gave Eventide's 61 pages in 2s and Roland's 32 in 0s. The same sweep uncached:

```
korg      310s      elektron  113s      roland  103s
boss       74s      eventide   66s      arturia   7s
```

If a scraper that fetches a page per device finishes faster than its device count in
seconds, it did not fetch anything. Arturia really is 7s for 183 devices, because it
is two JSON calls -- which is the point of preferring an API, and also why speed
alone cannot be the check.

**Search results lag badly on version numbers.** A search said Kontakt was on 8.9.0;
NI's own thread said 8.13.0. Believing the search would have meant reporting a
correct scraper as broken. Always confirm on the vendor's page.

**Compare the products against each other, not just against the site.** Eleven
identical results is the tell that no per-product fetch is happening at all, and it
shows up in the verification table long before anyone reads the vendor's page.

### Dates cannot be recovered later

Worth knowing before spending time on it: of 749 stored versions with a changelog and
no date, **three** contained a date-shaped string anywhere in that text. Eventide, 729
of them, had one. There is no backfill hiding in the data already collected.

Two sources look like dates and are not: a page-level "Last updated: July 10, 2024"
stamp, which belongs to the page rather than any release on it, and a "Revised
06/07/2017" against an instructions section. Attaching either to a version is the
fabrication this project exists to avoid.

A useful check on the first kind: fetch a second, unrelated page from the same
vendor. Yamaha's "Last updated: July 10, 2024" is byte-identical on the THR Remote
page and all three reface updater pages, because it is the end of the licence
agreement. A date that does not move between products is not about any product.

### A CMS timestamp is not a release date

The same trap wearing credentials. Eventide's site is WordPress and exposes a
`download` post type through the REST API, where every installer is a post with a
`date` field. A real API, a real ISO timestamp, named exactly like the thing being
looked for.

Count the distinct values before using it:

```
2025-12-11   80 installers
2021-08-16   31 installers
2024-03-06    4 installers
...          12 distinct days across 132 installers
```

Two Blackhole installers thirty seconds apart, and the guid still pointing at
`web-demo.aws.eventideaudio.com`. These are bulk imports from site migrations.
Believing them stamps eighty products with one invented release date, and every one
would look plausible in isolation.

The clustering test is the whole check and costs one request: **group the candidate
dates and count how many fall on the same day.** Genuine release dates spread out;
migration artefacts stack up. It is the same question as "does this date move between
products", asked of an API instead of a page.

### Match a date against a whole element, do not search the block

Where a date lives in its own tag, compare it to the element's *entire* text rather
than searching the flattened block. Ableton puts the release date in three places:
an `h4` as the first child, a `p` below an opening section heading, and on older
Live 11 point releases nowhere at all. An anchored search over the flattened text
finds only the first shape and cost 29 of 67 versions their date.

Searching rather than full-matching has the opposite failure: 12.4.5's changelog
mentions "May 5, 2025" while the release is dated August 26, 2026, and 11.0.12's
notes reference an issue from January 3, 2021 with no release date of its own. A
search finds both and attributes them.

```python
for child in list(body.children)[:6]:
    text = child.get_text(" ", strip=True)
    if DATE.fullmatch(text):          # the element is the date, not merely contains one
        ...
```

Bound the depth. Beyond the first few children you are inside the changelog.

### "This vendor publishes no dates" is a claim, not a finding

It ages exactly as badly as a version number, and it is usually recorded as settled
prose in a docstring where nothing re-checks it. Yamaha's said "No dates, checked
rather than assumed." Every downloads page had a `Last Update` column; the text
rendering hid it (see Step 4). Sixteen products carried no date for as long as that
sentence went unquestioned.

Before accepting it, re-run the search against the page rather than the docstring,
and check whether the product has a second page. reface pointed at
`/support/updates/reface_cp_updater_for_mac.html`, which is a EULA download gate
with no table at all; `/products/.../reface/downloads.html` lists all four products
with dates. **A URL that serves a file is not necessarily the page that describes
it** -- when a scraper's page is a download gate, look for the product's own
downloads page.

Where a vendor gives only a month -- Roland's `[ Ver.1.82 ] JUN 2023` -- store the
first of it and say so, rather than dropping the release date entirely.

## Before opening a PR

- Tests offline against a fixture page — never the network. See
  `test_tal_pairs_each_version_with_its_own_date` for the pattern.
- **Run the suite and read the result before pushing, not alongside it.** Running
  pytest and pushing in one step means the failure and the push happen together, and
  CI reports it before you do.
- If a URL changed, note that `sync_devices` now refreshes `firmware_page_url` on
  existing rows, so the fix reaches devices already in the database.
- **Existing firmware rows are refreshed too, but only filled or corrected, never
  emptied.** A scraper that stops reporting a date will not erase one already stored,
  so a parser fix reaches old rows while a regression cannot silently blank them.
  Wrong values the scrape no longer produces are not touched at all -- Elektron's
  twenty-two fabricated rows had to be deleted by hand.
- **Read `devices_synced` after the first real scrape.** `{'created': 16,
  'updated': 12}` means the existing twelve rows were refreshed and sixteen products
  are new. If `created` is close to the old device count, the names stopped matching
  and you have just duplicated the catalogue -- see Step 4b.
- Deleting a product from `KNOWN_PRODUCTS` leaves an orphan row in the DB that fails
  every scrape. Delete it explicitly, and check `my_devices` first.
