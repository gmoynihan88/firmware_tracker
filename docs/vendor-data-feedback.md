# Vendor data feedback

Notes on how easy it is to find out what firmware or software version a product is on,
gathered while writing and maintaining the 83 scrapers in this project. Written to be
shared with the vendors concerned, one section at a time.

Everything here was observed on the vendor's public site or support pages in September
2026, most of it on 15 September. Sites change, so check an item again before sending
it. "Publishes no version" means none was found on the product pages, downloads pages or
support site, not that none exists inside an app.

## The one request

For each product, a public page (or feed) at a stable URL that lists every release with
**version, release date and notes**. It does not need to be JSON; a plain HTML list or a
text file works. What matters is that it exists, that its URL does not change, and that
the version number there is the one the device reports about itself.

## Errors on vendor pages

Things that look like mistakes, and that a vendor would probably want to know about.

- **Peterson** — Each entry in the Firmware History on `/support/` stores its release
  as JSON in a single-quoted `data-update` attribute. An apostrophe in the notes ends the
  attribute early, so the JSON is invalid for **StroboStomp HD 1.0.34** and **StroboStomp
  LE 1.0.34** ("New settings screen parameter for 'Power Up Mute State'"). Those are the
  newest release for both products. Anything reading that attribute will skip them.
- **Tascam** — Every Sonicview-series support page (the consoles, SB-16D, IF-ST2110)
  shows the same three "Latest version info" tables with no label saying which unit
  each belongs to. On the SB-16D page the first says **Firmware V2.3.4**, which is
  the console's; SB-16D's own is V1.22, in the second. IF-ST2110's table writes its
  version as "V0109" while its download history calls the same release V1.0.9.
- **Zoom** — On the firmware page the F6 link reads **"F6 Firmware 2.00 + Audio Driver"**
  and downloads `F6_v2.20E.zip`.
- **Line 6** — The hardware filter on `/software/Firmware` leaves out 21 products that
  have firmware releases on that page, among them DT25/DT50, Spider V MkII, TonePort,
  Mobile Keys and the Bass PODxt line. It also offers entries with none ("No Hardware
  Required", iLok, Helix Stadium).
- **TC Electronic** — Clarity M Stereo's downloads include a "Firmware Release Note"
  typed as firmware with version "2", beside the real 2.0.3 and 2.1.3 files.
- **Apogee** — Every path on apogeedigital.com, a made-up one included, returns a
  Cloudflare 403 to scripts and to a headless browser alike. help.apogeedigital.com
  fails TLS and support.apogeedigital.com times out.
- **Fender** — The main site answers scripts with nothing and a browser with Cloudflare's
  challenge page. The Zendesk help centre (support.fender.com) works well and carries the
  Tone Master release notes.
- **Ableton** — Nothing links to the Live 11 release notes any more. The page still
  exists, but you can't reach it from the release-notes index.
- **Roland and Boss** — The category pages show only a few featured products. The full
  lists are only on the Updates & Drivers indexes under `/support/`.

## No public version at all

A product that updates through a desktop app with no public release list cannot be
checked by anyone without the app, and owners cannot tell whether they are behind.

- **Focusrite** — none of 28 interfaces; firmware ships inside Focusrite Control.
- **Keith McMillen Instruments** — none of 8 products.
- **Eventide** — 27 hardware products; firmware is fetched at run time by Eventide
  Device Manager.
- **Universal Audio** — no per-plug-in version for UAD plug-ins on the site or in the
  release notes, and UA Connect's manifest is encrypted. (UAFX pedals and OX are the
  opposite: fully published, dated release notes.)
- **Waves** — no per-plug-in versions, only the across-the-board generations.
- **Also** — Expressive E (Osmose, Touché), MOTU interfaces, PreSonus Studio One and
  hardware, Solid State Logic SSL 12/18 and UF8/UF1/UC1, Klanghelm's five paid plug-ins,
  Chase Bliss, Source Audio, Meris, Behringer, Intellijel Metropolix.

## Versions without dates

A version with no date tells an owner that something changed but not when.

| Vendor | Versions found | Dated |
|---|---:|---:|
| Eventide | 743 | 0 |
| Tokyo Dawn Labs | 267 | 0 |
| Novation | 112 | 0 |
| Audient | 87 | 0 |
| Moog | 68 | 0 |
| Polyend | 62 | 0 |
| Akai Professional | 46 | 0 |
| TC Electronic | 24 | 0 |
| Sequential | 22 | 0 |
| Cableguys | 21 | 0 |
| Zoom | 17 | 0 |
| HeadRush | 17 | 0 |
| IK Multimedia | 8 | 0 |
| Serato | 5 | 0 |

**Novation** is the easiest fix: its Components firmware API
(`components.novationmusic.com/api/v2/firmwares`) already lists every version without a
key. Adding a release-date field would complete it.

## Sources closed to automated readers

Both of these are the only public route to the version history, and robots.txt disallows
them for all crawlers.

- **Modartt** — the Pianoteq changelog page loads its content from `/api/`, which
  robots.txt disallows.
- **Steinberg** — maintenance announcements are found through the forum's `/search`,
  which robots.txt disallows.

A static changelog page, or allowing that one path, would make them readable.

## Good examples

Worth pointing others to.

- **Arturia** — two public JSON endpoints give every product's full firmware and software
  history, all dated.
- **Bitwig** — every Bitwig Studio release back to 2014 in one plain HTML table.
- **Cockos REAPER** — a single `whatsnew.txt` with 705 releases back to 2005.
- **Teenage Engineering** and **Squarp Instruments** — nearly every release dated,
  per product.
- **Synthstrom Audible**, **Dirtywave** and **OXI Instruments** — dated GitHub or GitLab
  releases.
- **Torso Electronics** — a documentation-site changelog per product.
- **Line 6** — every firmware release it has shipped, dated, on one page.

## How this was gathered

Each vendor's scraper in `src/scrapers/plugins/` records in its docstring what was
checked and ruled out. Figures come from the project database after a full scrape. The
project respects robots.txt, sends one request per second per vendor, and checks once a
day.
