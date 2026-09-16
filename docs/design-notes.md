# Reporting absence honestly

The hardest part of this project is not scraping. It is saying "I don't know" in a way
the app can act on, because a scraper that fills a gap with a plausible guess is worse
than one that reports nothing.

## Unknown versions are reported as unknown

Not every vendor publishes a version number.
[vendor-data-feedback.md](vendor-data-feedback.md) lists which vendors publish no
version or no dates, errors found on vendor pages, and the sources worth copying.

**Universal Audio publishes no per-plugin versions**: not on their site, not in their
release notes (which list changes by month with no version numbers), and their installer
manifest is encrypted. An earlier version of that scraper carried a hardcoded table whose
ten entries matched the plugins installed on the developer's machine, because that is
where they came from. It reported every product as current by construction and could not
detect an update. Those products now report no version, which renders as "Firmware
Unknown", and link to UA's release notes.

**Eventide is a similar case for hardware.** The H90 downloads page shows version 2.2.0,
which belongs to a companion app rather than the pedal; pedal firmware ships through
Eventide's device manager and is not published anywhere.

**The reverse is worth stating, because assuming it cost this project 22 products.** UA's
UAFX pedals are delivered by UA Connect too — their release notes open with "To update
your pedal's firmware, use UA Connect" — and are published in full, sixteen dated
versions back to 2021. Shipping firmware through a vendor's own installer says nothing
about whether the version is published.

## Three outcomes, not two

A scrape distinguishes:

- `devices_failed` — a fetch or parse that broke.
- `devices_without_firmware` — a product the vendor publishes nothing for.
- `devices_not_checked` — the time budget ran out.

Collapsing the first two would either hide a real breakage or report one every run.

## Products that will never report a version say so

122 devices have no version, and for 92 a scraper has established why: the catalogue
shows `not published` where the vendor publishes no version anywhere, and `no firmware`
where the product takes no updates at all. The other 30 stay an em-dash, because nobody
has checked and guessing is the thing this avoids.

That split is what makes the absence list usable. `devices_without_firmware` carries over
a hundred entries on every sweep, so a product that goes silent tomorrow joins a crowd
nobody reads; `devices_unexplained` holds only the ones with no recorded reason, and it is
the list that should be shrinking.

## Release dates are the vendor's, or nothing

1,375 of 1,923 current versions carry a release date. That is what the vendor publishes,
not what the scraper managed to read — some list a version with no date anywhere on the
page. The catalogue shows an em-dash rather than substituting the date the version was
first seen, which would read as a release date and would be wrong.

The same rule killed a tempting shortcut: a page-level "Last updated" stamp belongs to the
page, not to any release on it, and "Revised 06/07/2017" against an instructions section
is not a firmware date either.
