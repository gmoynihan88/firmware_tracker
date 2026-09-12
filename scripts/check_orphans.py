"""Find rows whose parent no longer exists.

SQLite does not enforce foreign keys unless each connection asks it to, and until
`enforce_foreign_keys` was added it never did. Combined with a service that deleted
through `delete(X).where(...)` -- a Core statement the ORM's declared cascades never
see -- deleting one device model left its firmware versions behind pointing at an id
that was gone. Two of them sat in the development database, reachable by nothing and
counted by nothing, until a new catalog column counted 201 dated versions and
rendered 200.

Both holes are closed, so this finds only debris written before the fix. It is worth
keeping because a database outlives the bug that damaged it, and this one is meant to
accumulate years of history.

    .venv/bin/python scripts/check_orphans.py          # report
    .venv/bin/python scripts/check_orphans.py --fix    # delete what it found

Exits 1 when it finds something, so it can gate a deploy. Take a backup before
--fix: scripts/backup_db.sh
"""

import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# (child table, its foreign key, parent table). Ordered child-first, so deleting in
# sequence never strands something this pass already counted.
RELATIONS = [
    ("notifications", "my_device_id", "my_devices"),
    ("notifications", "firmware_version_id", "firmware_versions"),
    ("firmware_versions", "device_model_id", "device_models"),
    ("my_devices", "device_model_id", "device_models"),
    ("device_models", "manufacturer_id", "manufacturers"),
    ("scrape_runs", "manufacturer_id", "manufacturers"),
]


def orphans(db, child, key, parent):
    # scrape_runs.manufacturer_id is nullable -- a run for a scraper with no
    # manufacturer row yet is expected, not debris.
    return db.execute(f"""
        SELECT c.id FROM {child} c
        LEFT JOIN {parent} p ON p.id = c.{key}
        WHERE c.{key} IS NOT NULL AND p.id IS NULL
    """).fetchall()


def main() -> int:
    fix = "--fix" in sys.argv
    database = ROOT / "firmware_tracker.db"
    if not database.exists():
        print(f"No database at {database}")
        return 2

    db = sqlite3.connect(database)
    total = 0

    for child, key, parent in RELATIONS:
        rows = orphans(db, child, key, parent)
        if not rows:
            continue
        total += len(rows)
        ids = [row[0] for row in rows]
        print(f"{child}.{key} -> {parent}: {len(ids)} orphaned (ids {ids[:10]}"
              f"{'...' if len(ids) > 10 else ''})")
        if fix:
            db.executemany(f"DELETE FROM {child} WHERE id = ?", [(i,) for i in ids])

    if fix and total:
        db.commit()
        print(f"\nDeleted {total} rows.")
    elif total:
        print(f"\n{total} orphaned rows. Re-run with --fix to delete them.")
    else:
        print("No orphaned rows.")

    return 1 if total and not fix else 0


if __name__ == "__main__":
    sys.exit(main())
