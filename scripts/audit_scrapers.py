"""Find scrapers that are wrong while reporting success.

Every scraper repaired recently looked healthy first. Elektron reported no failures
for eleven products while giving all of them the same two versions, read off a news
blurb. Universal Audio ran in 0.01s with everything green while reporting the
versions installed on the developer's own laptop. `devices_failed` stays empty in
both cases, so the scrape summary cannot be the thing you check.

Three checks, none of which need a network fetch:

  duplicates  one version claimed by many products of the same vendor
  unreachable methods and constants nothing in the file references
  effort      a field the scraper sets and the database never receives

Run it with no arguments. Anything it prints is a question, not a verdict -- some
vendors really do ship one firmware across a product family.

    .venv/bin/python scripts/audit_scrapers.py

A clean result is only worth something if the checks can fail. Point it at a commit
where something was known to be wrong before believing an empty report:

    git stash && git checkout <commit-before-a-fix>
    .venv/bin/python scripts/audit_scrapers.py

Doing that against the commit before QSC's orphaned parser was removed prints exactly
that one method, which is how this script was shown to work rather than assumed to.
"""

import ast
import pathlib
import re
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGINS = ROOT / "src/scrapers/plugins"
TESTS = ROOT / "tests/test_basic.py"

# The base class calls these; a plugin never references them itself.
FRAMEWORK = {
    "fetch_device_list", "fetch_firmware_versions", "__init__", "scraper_type",
    "close", "fetch_page", "fetch_page_js", "fetch_json", "parse_html",
}

FIELDS = {"release_date": "release_date", "download_url": "download_url",
          "changelog": "changelog_raw"}


def plugin_sources():
    for path in sorted(PLUGINS.glob("*.py")):
        if path.name != "__init__.py":
            yield path, path.read_text()


def slug_of(source: str):
    found = re.search(r'manufacturer_slug\s*=\s*"([^"]+)"', source)
    return found.group(1) if found else None


def check_duplicates(db) -> int:
    """One version across many products of a vendor.

    This is what exposed Elektron: eleven products, two versions, every product
    carrying both. Real families do share a release -- MC-101, MC-707 and VERSELAB
    MV-1 all run Roland System Program 1.82 -- so the output needs a look rather
    than a fix. The question to ask is whether the vendor's pages agree.

    Only current versions count. Including history flags every vendor whose products
    each passed through a 1.0x on their way up, which is most of them.
    """
    rows = db.execute("""
        SELECT m.name, fv.version, COUNT(DISTINCT dm.id) AS products,
               (SELECT COUNT(*) FROM device_models d2 WHERE d2.manufacturer_id = m.id) AS total
        FROM firmware_versions fv
        JOIN device_models dm ON dm.id = fv.device_model_id
        JOIN manufacturers m ON m.id = dm.manufacturer_id
        WHERE fv.is_latest = 1
        GROUP BY m.name, fv.version
        HAVING products > 2 AND products >= total * 0.6
        ORDER BY products DESC
    """).fetchall()

    print("== one version shared across most of a vendor's catalogue ==")
    for name, version, products, total in rows:
        print(f"   {name:<20} {version:<10} on {products} of {total} products")
    if not rows:
        print("   none")
    return len(rows)


def check_unreachable() -> int:
    """Methods and constants nothing references.

    QSC had a _parse_k2_firmware_page that read the release date correctly and was
    called from nowhere, so the date reached the database once and could not be
    produced again.
    """
    test_src = TESTS.read_text() if TESTS.exists() else ""
    findings = []

    for path, source in plugin_sources():
        tree = ast.parse(source)
        used = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                used.add(node.attr)
            elif isinstance(node, ast.Name):
                used.add(node.id)

        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            for item in cls.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    name, kind = item.name, "method"
                elif isinstance(item, ast.Assign) and len(item.targets) == 1 \
                        and isinstance(item.targets[0], ast.Name) \
                        and item.targets[0].id.isupper():
                    name, kind = item.targets[0].id, "const"
                else:
                    continue
                if name in FRAMEWORK or name in used:
                    continue
                where = "tests only" if name in test_src else "nowhere"
                findings.append((path.name, kind, name, item.lineno, where))

    print("\n== defined and never referenced ==")
    for fname, kind, name, line, where in findings:
        print(f"   {fname:<24} {kind:<7} {name:<28} line {line:<5} ({where})")
    if not findings:
        print("   none")
    return len(findings)


def check_effort(db) -> int:
    """A field the scraper sets that never reaches the database.

    Boss carries a careful two-format date extractor for a page layout that no longer
    exists. The code runs; the pattern never matches. Static analysis cannot see this.

    A scraper that deliberately passes None -- Eventide's release_date, because its
    release notes carry no dates -- looks identical here, so read the comment before
    concluding anything.
    """
    findings = []
    for path, source in plugin_sources():
        slug = slug_of(source)
        if not slug:
            continue
        total = db.execute("""SELECT COUNT(*) FROM firmware_versions fv
            JOIN device_models dm ON dm.id = fv.device_model_id
            JOIN manufacturers m ON m.id = dm.manufacturer_id AND m.slug = ?""",
            (slug,)).fetchone()[0]
        if not total:
            continue
        for keyword, column in FIELDS.items():
            if not re.search(rf"\b{keyword}\s*=", source):
                continue
            have = db.execute(f"""SELECT COUNT(*) FROM firmware_versions fv
                JOIN device_models dm ON dm.id = fv.device_model_id
                JOIN manufacturers m ON m.id = dm.manufacturer_id AND m.slug = ?
                WHERE fv.{column} IS NOT NULL AND fv.{column} != ''""",
                (slug,)).fetchone()[0]
            if have == 0:
                findings.append((path.name, keyword, total))

    print("\n== sets a field the database never receives ==")
    for fname, keyword, total in findings:
        print(f"   {fname:<24} {keyword:<14} 0 of {total} rows")
    if not findings:
        print("   none")
    return len(findings)


def main() -> int:
    database = ROOT / "firmware_tracker.db"
    if not database.exists():
        print(f"No database at {database}. Run a scrape first.")
        return 2

    db = sqlite3.connect(database)
    total = check_duplicates(db) + check_unreachable() + check_effort(db)
    print(f"\n{total} things to look at.")
    # Always exits 0: every finding needs judgement, so this is not a gate.
    return 0


if __name__ == "__main__":
    sys.exit(main())
