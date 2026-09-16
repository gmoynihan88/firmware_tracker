# Scraping load

Several of these vendors are very small operations, so the defaults are set to keep
request volume low. **These are worth keeping if you fork it.** Every instance scrapes
independently, so the load scales with the number of people running it.

- **One request per second per manufacturer**, and a daily check rather than hourly.
- **Conditional requests** (`If-None-Match` / `If-Modified-Since`), so an unchanged page
  returns `304` with no body. Not every vendor sends validators; for those that do, it
  saves the full page on every run.
- **`SCRAPE_CACHE=1`** serves repeat requests from disk during development. Working on a
  scraper means fetching the same page dozens of times, and a cached run is 35× faster as
  well as 35× less traffic. Leave it off anywhere real — a cached run cannot discover a
  new version.

## Three vendors check a slice of their catalogue per run

**Korg** is the one vendor with no listing covering more than a single product, and 164
product pages at ~4.8s each is 794s against a 900s hard timeout — the first attempt was
killed by it. Candidates are sorted and strided into five batches of 33, picked by day of
year, so a run costs ~160s and every product is seen within five days. `KORG_FULL_SWEEP=1`
does all five in one run, for a first import or a catch-up.

**Roland and Boss** do the same. Their Updates & Drivers indexes list every product (580
and 126), and only each product's own listing says whether it takes firmware, so a full
Roland pass measured 1,945s. Roland reads a sixth of its index per run (~217s) and Boss
half (~107s). `ROLAND_FULL_SWEEP=1` and `BOSS_FULL_SWEEP=1` read everything at once;
Roland's takes longer than the scheduler's hard timeout, so it is for a manual catch-up
only.

## Scrapers identify as a browser

Some vendors reject anything else, so requests carry a browser User-Agent. The trade-off
is real: a vendor cannot tell who is calling or ask you to stop. Every other default here
leans the other way — daily rather than hourly, one request per second, conditional
requests, and batching for the three vendors that would otherwise cost a thousand
requests a day.
