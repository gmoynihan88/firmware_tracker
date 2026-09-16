"""Keep the scraper and device counts in README.md and CLAUDE.md in step with the code.

Every scraper PR used to edit the same places by hand -- "This scrapes N
manufacturers", "Scrapes N manufacturers", "(N scrapers)", "N devices across N
vendors", and CLAUDE.md's "N manufacturer scrapers" -- and they drifted: CLAUDE.md
once said 24 while the repo had 37.

    .venv/bin/python scripts/update_readme_counts.py           # rewrite the counts
    .venv/bin/python scripts/update_readme_counts.py --check   # exit 1 if any are stale

The scraper count comes from the plugin registry. The device count comes from the
database and is left alone when there is none, as in CI; the test suite checks the
scraper counts, which need no database.

The Supported manufacturers table stays hand-written -- which column a vendor sits in,
and the product named beside it, are editorial -- but vendors missing from it are
listed, and fail --check. The table is read wherever it sits in that section, including
inside a <details>.
"""

import argparse
import pathlib
import re
import sqlite3
import sys
from typing import Iterable, List, Optional, Tuple

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATABASE = ROOT / "firmware_tracker.db"

README_SCRAPER_COUNTS = [
    re.compile(r"(This scrapes )\d+( manufacturers)"),
    re.compile(r"(\*\*Scrapes )\d+( manufacturers\*\*)"),
    re.compile(r"(# One file per manufacturer \()\d+( scrapers\))"),
]
README_DEVICES = re.compile(r"[\d,]+( devices across )\d+( vendors)")
CLAUDE_SCRAPER_COUNT = re.compile(r"(with )\d+( manufacturer scrapers)")


def apply_counts(text: str, patterns: Iterable[re.Pattern], scrapers: int) -> Tuple[str, List[str]]:
    """Put the scraper count into every pattern; report the patterns that matched nothing."""
    unmatched = []
    for pattern in patterns:
        text, found = pattern.subn(lambda m: f"{m.group(1)}{scrapers}{m.group(2)}", text)
        if not found:
            unmatched.append(pattern.pattern)
    return text, unmatched


def apply_devices(text: str, devices: Optional[int], scrapers: int) -> Tuple[str, List[str]]:
    """Put the device and vendor counts into the Usage sentence."""
    replacement = (lambda m: f"{devices:,}{m.group(1)}{scrapers}{m.group(2)}") if devices is not None else (
        lambda m: re.sub(r"\d+(?= vendors)", str(scrapers), m.group(0)))
    text, found = README_DEVICES.subn(replacement, text)
    return text, [] if found else [README_DEVICES.pattern]


def missing_from_table(readme: str, names: Iterable[str]) -> List[str]:
    """Manufacturer names with no cell in the Supported manufacturers table.

    Cells drop the asterisk and the product in brackets -- "Arturia\\*", "Apple (Logic
    Pro, MainStage)" -- and may shorten the name: "Keith McMillen" covers "Keith
    McMillen Instruments".
    """
    section = readme.split("## Supported manufacturers", 1)[-1].split("\n## ", 1)[0]
    # Every table row in the section, rather than the second paragraph block: the table
    # sits inside a <details> so a long vendor list does not dominate the README, and
    # positional parsing read the <summary> instead and reported every vendor missing.
    rows = [line for line in section.splitlines() if line.startswith("|")]
    cells = {re.sub(r"\\\*|\s*\(.*\)", "", cell).strip()
             for row in rows for cell in row.strip("|").split("|")} - {""}
    cells -= {"Hardware", "Plugins"}
    cells = {cell for cell in cells if set(cell) - set("-: ")}
    return sorted(name for name in names
                  if not any(name == cell or name.startswith(cell + " ") for cell in cells))


def device_count(database: pathlib.Path = DATABASE) -> Optional[int]:
    if not database.exists():
        return None
    with sqlite3.connect(database) as db:
        return db.execute("SELECT count(*) FROM device_models").fetchone()[0]


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="change nothing; exit 1 if anything is stale")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(ROOT))
    from src.scrapers.registry import ScraperRegistry

    scrapers = ScraperRegistry.get_all_scrapers()
    count, devices = len(scrapers), device_count()

    readme_path, claude_path = ROOT / "README.md", ROOT / "CLAUDE.md"
    readme, claude = readme_path.read_text(), claude_path.read_text()
    new_readme, unmatched = apply_counts(readme, README_SCRAPER_COUNTS, count)
    new_readme, unmatched_devices = apply_devices(new_readme, devices, count)
    new_claude, unmatched_claude = apply_counts(claude, [CLAUDE_SCRAPER_COUNT], count)
    missing = missing_from_table(new_readme, (cls.manufacturer_name for cls in scrapers.values()))

    for pattern in unmatched + unmatched_devices + unmatched_claude:
        print(f"no text matched {pattern!r} -- was the sentence reworded?")
    for name in missing:
        print(f"not in README's Supported manufacturers table: {name}")

    stale = [path.name for path, old, new in ((readme_path, readme, new_readme), (claude_path, claude, new_claude))
             if old != new]
    print(f"{count} scrapers, {'no database' if devices is None else f'{devices:,} devices'}; "
          f"{'stale: ' + ', '.join(stale) if stale else 'counts current'}")
    if not args.check:
        readme_path.write_text(new_readme)
        claude_path.write_text(new_claude)
        stale = []
    return 1 if stale or missing or unmatched or unmatched_devices or unmatched_claude else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
