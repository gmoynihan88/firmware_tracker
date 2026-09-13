---
name: scraper-batch
description: Run a campaign of adding several manufacturer scrapers — survey the candidates, build one, debug, test, fold what was new back into the skills, repeat. Use when asked to add multiple vendors, to work through a priority list, or when deciding which vendors are worth adding at all.
---

# Building a batch of scrapers

Sixteen vendors were added to this repo in two days with the loop below. It is not
`add-scraper` run sixteen times: the survey happens **once for the whole candidate
list**, the skills get updated **between vendors rather than at the end**, and each
vendor ships as its own PR.

Use `add-scraper` for the shape of the class and `debug-scraper` for the ladder when
one misbehaves. This skill is the order the work goes in, and the parts that only
show up when you do it repeatedly.

```
survey all candidates  ->  pick the cheapest feasible one
                              |
        +---------------------+
        v
   extract in a scratch script  ->  write the class  ->  offline tests per trap
        ^                                                        |
        |                                                        v
   fold back what was new  <-  merge  <-  PR  <-  live run + database
        |
        +--> next vendor
```

## Step 1 — Survey every candidate before building any

Rank first, by what the catalogue gains rather than by what looks easy. Then probe
all of them in one pass, because the probe is cheap and the ranking changes once you
know which ones publish anything at all.

**A survey verdict is one of four**, and the last two are worth writing down so
nobody re-probes them:

| Verdict | Meaning | Example |
|---|---|---|
| `api` | a machine-readable source exists | Arturia, Novation, Fender |
| `html` | versions are in markup, reachable | Zoom, Empress, Kemper |
| `gated` | published but behind a login or a challenge | Bitwig's `/previous_releases/` |
| `none` | nothing is published anywhere | Chase Bliss, Meris, Behringer |

The probe, run against every candidate at once. It answers "is there a version-shaped
string anywhere on this page" — not "can I parse it", which comes later:

```bash
.venv/bin/python - <<'PY'
import asyncio, re
from src.scrapers.base import BaseScraper

class Probe(BaseScraper):
    manufacturer_name = "probe"; manufacturer_slug = "probe"
    manufacturer_website = "https://example.com"
    async def fetch_device_list(self): ...
    async def fetch_firmware_versions(self, a, b): ...

CANDIDATES = [
    ("vendor-a", "https://vendor-a.com/support/downloads/"),
    ("vendor-a-control", "https://vendor-a.com/support/zzqx-not-a-product-9f3a/"),
]
VERSION = re.compile(r"\b[vV]?\d+\.\d+(?:\.\d+)?\b")

async def main():
    scraper = Probe()
    for name, url in CANDIDATES:
        html = await asyncio.wait_for(scraper.fetch_page(url), timeout=45)
        text = scraper.parse_html(html).get_text(" ", strip=True) if html else ""
        hits = VERSION.findall(text)[:6]
        print(f"{name:<22} {len(html or ''):>8}b text={len(text):>6} {hits}")
    await scraper.close()

asyncio.run(main())
PY
```

**Include a control slug for every vendor**, not one for the batch — endpoints that
answer identically to anything are per-vendor behaviour. See `debug-scraper` step 1
for why a plausible-sounding fake name is not a control.

**`gated` is the verdict most often given wrongly, because every page has a login
form in its chrome.** Bitwig's `/previous_releases/` was recorded here as "renders a
login" and left unbuilt for that reason; a plain fetch returns 9,003 characters of
text with every release back to 1.0, dated. What the probe saw was the site's header
login widget, which is on every page including the ones that work.

PSPaudioware is the same probe output meaning the opposite, and the two together give
the test. Its `/downloads` really is gated: the page **body** is the login form --
"You need to be logged into your PSP account to proceed!" -- and there is no version
list anywhere on it. So: a login in the chrome beside content is not a gate; a login
*instead of* content is. Read what the probe prints rather than grepping it for
"login", and look for the version list.

A real gate is also not the end of the vendor. PSP's public product pages carry a
30-day-trial link each, and the version is in the installer's filename -- 43 of its
57 plug-ins, without an account.

The same probe shows the other reason to read the output rather than trust the hit
count: Bitwig's download page yields `['6.1.1', '24.04', '24.04']`, and the last two
are Ubuntu 24.04 -- an OS requirement, not a release.

**A JS shell is not a verdict.** Akai returned an empty shell on a guessed URL and
turned out to serve Gatsby `page-data` JSON; Arturia and Novation both looked dead
and both had clean APIs. Three vendors now where the first impression was wrong, so
`none` requires having tried the support platform and the browser network capture,
not just a fetch.

## Shapes seen so far — pattern-match before probing blind

Most vendors are one of these. Recognising the shape early saves the whole search:

| Shape | How it announces itself | Built here |
|---|---|---|
| JSON API the page itself calls | network capture shows `/api/…` returning JSON | Arturia, Novation, Modartt, TC Electronic |
| Zendesk Help Center | site is blocked or empty; `support.<vendor>.com/api/v2/help_center/…` answers | Universal Audio, Fender, Keith McMillen |
| Gatsby `page-data` | `/page-data/…/page-data.json`, plus `staticQueryHashes` | Akai |
| Next.js RSC payload | `self.__next_f.push([1,"…"])` in the HTML | TC Electronic |
| One page covers the range | a single `/firmware/` or `/downloads/` listing every product | Zoom, Line 6, GForce, Empress |
| JS-rendered page | plain fetch returns shell; Playwright returns content | Kemper, Empress |
| One page per product | no listing carries versions | Korg (164 pages — needs batching) |
| Publishes nothing | every version on the page belongs to an editor app | Focusrite, Keith McMillen |

**Check the one-page shape before designing anything per-device.** It is the
difference between Zoom's single fetch and Korg's 794 seconds.

## Step 2 — Extract in a scratch script before writing the class

Every vendor in this batch was validated in a throwaway script first: fetch the page,
print `name -> version` for the whole catalogue, read the list. Only then write the
plugin.

Writing the class first means debugging the parser and the plumbing at the same
time, and the parser is where all the surprises are. The scratch script is also where
the traps surface, and **the traps are what the tests will be**.

Done means: a printed list of every product with its version, **checked by eye
against two or three of the vendor's own pages**. Two specific things to look for,
both of which have shipped wrong here:

- **A product missing from the list.** Zoom writes its links two ways, `H2n Firmware`
  and `R20 System Version 3.30`; the first filter looked like a clean seventeen-product
  read and was silently dropping three. Count the products on the page by hand and
  compare. A pattern stricter than the site reads exactly like a vendor that
  publishes less than it does.
- **A version that belongs to something else.** File sizes (`Firmware ReadMe
  (76.74 kB)` → 76.74), editor apps, drivers, manual revisions. See `debug-scraper`
  step 4 for the full table.

## Step 3 — Write the class

`add-scraper` has the shape. Two things this batch settled:

**Resolve once.** One fetch in a `_load()` that caches on the instance, with both
`fetch_device_list` and `fetch_firmware_versions` reading from it. Thirteen of the
last sixteen use this shape.

**List only products whose version you could actually read.** Fractal's homepage
links Axe-Fx II, whose page states its firmware in a shape none of the patterns
match. Listing it anyway adds a row that reports nothing on every run forever — the
Focusrite failure, self-inflicted on one product. If the vendor genuinely publishes
nothing for a product you still want catalogued, set
`firmware_availability="not_published"` so the UI says why instead of showing a blank
that looks like a broken scraper.

## Step 4 — One test per trap, and prove one of them can fail

Offline, against a fixture string. Never the network.

Write one test per surprise found in step 2, named for the surprise rather than for
the method. The Zoom tests read as a list of everything that page does wrong:
`test_zoom_trusts_the_filename_over_a_stale_title`,
`test_zoom_ignores_accessibility_files`,
`test_zoom_collapses_the_windows_and_mac_builds_of_one_product`.

**Then break the code on purpose and watch the test fail.** This takes thirty
seconds and has caught tests that asserted nothing twice in this repo — once because
Jinja renders undefined attributes as falsy, so a template-only sabotage changed
nothing:

```bash
cp src/scrapers/plugins/VENDOR.py /tmp/v.bak
# invert the specific decision the test exists to defend, then:
.venv/bin/pytest tests/test_basic.py -k VENDOR -q | grep -E "passed|failed"
cp /tmp/v.bak src/scrapers/plugins/VENDOR.py
.venv/bin/pytest tests/test_basic.py -k VENDOR -q | grep -E "passed|failed"
```

Expect `1 failed` then all passed. If the sabotage passes, the test is decoration.

Add the slug assertion in `tests/test_basic.py::test_api_scrapers` while you are here
— it is the one wire-up step with no other symptom when forgotten.

## Step 5 — Live run, then the database

Run the whole catalogue through the finished scraper against the live site, with the
cache **off**, and read every row:

```bash
SCRAPE_CACHE=false .venv/bin/python - <<'PY'
import asyncio
from src.scrapers.plugins.VENDOR import CLASS
async def main():
    s = CLASS()
    listing = await asyncio.wait_for(s.fetch_device_list(), timeout=120)
    print(f"success={listing.success} devices={len(listing.devices)}")
    for d in listing.devices:
        r = await s.fetch_firmware_versions(d.name, d.firmware_page_url)
        print(f"  {'OK ' if r.success else 'FAIL'} {d.name:<16} "
              f"{[f.version for f in r.firmware_versions][:3]}")
    await s.close()
asyncio.run(main())
PY
```

`.env` sets `SCRAPE_CACHE=true`, so a run that does not override it proves the parser
works against saved HTML and nothing about the vendor. The tell is timing: Eventide's
61 pages came back in 2s.

Then scrape into the database with `NOTIFY_TRANSPORT=none` and read
`devices_synced`. A `created` count near the vendor's full device total on a **second**
run means the names stopped matching and you have just orphaned the old rows.

## Step 6 — One vendor, one branch, one PR

```bash
git checkout main && git checkout -b vendor-scraper
git log --oneline main..HEAD   # must print nothing
```

**Check out main first.** Branching from the branch you are on has stacked PRs twice
here, and it is invisible until review shows an unrelated vendor's commits.

**Do not let one PR accumulate vendors.** A PR that grew to cover several had to be
split by hand afterwards. Two genuinely tiny related vendors shipping together
(iConnectivity and Keith McMillen) is fine; three is a split waiting to happen.

Each PR: the scraper, its tests, the slug assertion, and the README manufacturer
table plus counts. The PR body is where the traps go — it is the only place a
reviewer learns that the vendor's own link text is stale.

## Step 7 — Fold back what was new, before the next vendor

This is the step that makes a batch cheaper than its parts, and the one that gets
skipped. Do it **while the surprise is fresh**, not at the end of the batch.

The skills are already long. The bar for adding to one:

- **Add it** if it cost more than ten minutes to work out, and the next vendor could
  hit it blind. Yamaha's dates — hidden because flattening a table puts each date
  before the *next* row's name — is the model: a whole vendor was written off as
  "publishes no dates" because of it.
- **Add it** if it is a new *shape* (a new platform, a new payload format). Those go
  in the table above, one row.
- **Do not add** a per-vendor quirk with no general lesson. That belongs in the
  scraper's docstring, where the next person to touch that file will read it.
- **Do not add** a second example of a trap already documented. Sharpen the existing
  entry instead.

The scraper docstring is the other half of this. Write down what you **ruled out**,
with dates — `universal_audio.py` and `keith_mcmillen.py` record every source checked,
so "does this vendor publish anything?" is answered by reading rather than by
repeating the search. A negative result that is not written down gets re-derived.

## Between vendors, and at the end of a batch

Per vendor, after merging:

```bash
.venv/bin/python scripts/audit_scrapers.py     # wrong while reporting success
.venv/bin/python scripts/check_orphans.py      # names stopped matching
```

`audit_scrapers.py` catches one version claimed across most of a catalogue, code
nothing references, and fields set that never reach the database. All three have
caught scrapers that reported no failures.

At the end of the batch:

- **A full uncached sweep of everything**, not just the new ones. About 17 minutes
  for 37 vendors: korg 310s, elektron 113s, roland 103s, boss 74s, eventide 66s,
  everything else under 30s.
- **README counts** — vendor count, device count, the manufacturer table. Three
  separate places, and they drift.
- **`CLAUDE.md`'s scraper count**, which drifted to 24 while the repo had 37.
- **Tag a release.** A batch is a release's worth of change.

## What a batch actually costs

Measured over sixteen vendors, so a campaign can be planned rather than guessed:

- **A feasible vendor is about an hour**, survey to merged PR.
- **Roughly four in five candidates are feasible.** Sixteen built, four settled as
  `none`.
- **The expensive part is never the class.** It is finding the source and working out
  which numbers on the page are the product's.
- **Catalogue size does not predict effort.** Arturia — the largest at 183 devices —
  took the least time of any vendor in the batch, because two JSON endpoints answered
  everything. Akai, at 28 products, took longer: versions in prose, next to file
  sizes.

## Traps that recur across vendors

One line each. The detail is in `debug-scraper`; this is the checklist to run against
a new vendor's page before believing an extraction.

- **Most versions on a support page are not the product's** — editor apps, drivers,
  transfer tools, manual revisions.
- **The vendor's own link text goes stale.** Zoom's F6 link says 2.00 and points at
  `F6_v2.20E.zip`. Prefer the artefact over the prose describing it.
- **One product, several downloads** — Windows and macOS builds of one firmware.
  Key on the product, keep the highest version.
- **Suffixes are not all revisions.** `H2n_v3.00E` is 3.00 with a language marker;
  `H6_v2.50a` is a real 2.50a.
- **A vendor writes the same thing two ways**, and a filter fitted to one drops the
  other silently. Zoom: "Firmware" and "System Version". Fractal: three wordings.
  **This applies to hosts as well as words** -- PSPaudioware serves the same
  installers from its own CDN and from an S3 bucket, so anchoring the pattern on the
  hostname silently took 31 of 43 products. Anchor on the artefact, not on who serves
  it.
- **Product names differ from the database's** — trademark symbols, typographic
  characters, casing, renames.
- **Pair a version with its own date**, from the same entry.
- **Page-level "last updated" stamps are not release dates.** Neither is "Revised
  06/07/2017" against an instructions section.
- **Never leave a hardcoded version table as a silent fallback.**
