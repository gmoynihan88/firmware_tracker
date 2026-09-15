---
name: verify-ui-change
description: Prove a CSS or template change leaves every page looking the same, by rendering each page on main and on the working tree and diffing every element's computed style. Use when splitting, reordering or deduplicating stylesheets, renaming classes, or restructuring templates -- any change meant to be visually a no-op.
---

# Verifying a change that should not change how the site looks

The tests cannot see the cascade. Splitting `style.css` into nine files first loaded
`.section-header h2` before `.detail-section h2`; both have the same specificity, so
the later one won and every section heading on the device page changed size, colour,
border and spacing. All 520 tests passed. A computed-style diff found it in one run.

## Run it

```bash
.venv/bin/python scripts/compare_css.py                 # working tree vs main
.venv/bin/python scripts/compare_css.py --ref v0.6.0    # vs a tag or commit
.venv/bin/python scripts/compare_css.py --pages /catalog "/catalog#dialog"
```

It checks REF out into a temporary worktree, copies the database once, starts four
servers on free ports (each checkout open, and each with auth on so `/login`
renders), then loads every page at 1280px and 390px on both sides and compares every
element. Exit 0 means no element on any page differs. Takes about two minutes, most
of it the catalog's 13,000 elements.

**Commit first, or at least know what REF is.** The "new" side is the working tree as
it is when the servers start.

## Reading the output

    1280 /devices/1               elements=   101 differing=16
           h2: {'border-bottom-width': ('0px', '1px'), 'font-size': ('14px', '13px'), ...}

- **Look at the first differing element that is not a container.** Heights of `body`,
  `main` and layout divs change because something inside them grew; the `h2` above is
  the cause and the containers are consequences.
- **`DOM differs`** means the two sides rendered different markup -- a template
  changed, or the database copy is not what you think. Styles cannot be compared.
- **A difference on every element of every page** is the harness, not the change. It
  has happened twice: custom properties enumerate in declaration order (fixed by
  sorting), and infinite animations never settle (fixed by switching them off). If a
  third source appears, fix the script before believing it.

## Fixing a real difference

Fix the **order**, not the selectors. The rules were right before the move; what
changed is which one loads later. Move the losing section after the rule it used to
follow, and leave a comment saying which rule it overrides -- the next person to tidy
the files will otherwise undo it. `static/css/device.css` has the example.

## What it cannot see

`:hover`, `:focus`, `:active`, and states reached by interaction other than the
catalog's version-history dialog (`/catalog#dialog` opens it). For a reorder, check
those statically:

1. List rule pairs whose relative order the change flips, with the same specificity
   and overlapping properties.
2. For each, ask whether one element can match both. Grep the templates for an
   element carrying both classes, or one nested inside the other.

For the style.css split that was 42 candidate pairs and no element matching both.

## Not a test

Chromium is not installed in CI, so this stays a local check. Put its result in the
PR description -- pages, widths, differing count -- the way #127 did.
