import json
import os
from datetime import datetime
import sqlite3
from pathlib import Path

import pytest

from tests.support import test_engine, test_session_maker


def test_alembic_prefers_database_url_over_the_ini(tmp_path, monkeypatch):
    """Migrations must follow the app's database, not alembic.ini's relative path.

    alembic.ini carries a sync sqlite:/// URL while the app uses an async one, so the
    two can disagree about which file they mean. In a container they always do: the
    database is on a mounted volume, and migrating alembic.ini's relative path would
    quietly create and migrate a second, empty database inside the image -- leaving
    the real one unmigrated and the failure invisible until a query hits a missing
    column.
    """
    import subprocess
    import sys

    target = tmp_path / "volume" / "firmware_tracker.db"
    target.parent.mkdir()

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(Path(__file__).parent.parent),
        env={**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{target}"},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    # The database named by DATABASE_URL exists and carries the schema.
    assert target.exists()
    with sqlite3.connect(target) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "manufacturers" in tables
    assert "alembic_version" in tables


def _integrity(tables: list) -> bool:
    """Run the real check against an in-memory database with these tables."""
    import sqlalchemy
    from src.database import _check_db_integrity

    engine = sqlalchemy.create_engine("sqlite://")
    with engine.begin() as conn:
        for table in tables:
            conn.execute(sqlalchemy.text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
        return conn.run_callable(_check_db_integrity) if hasattr(conn, "run_callable") else _check_db_integrity(conn)


def test_a_database_with_no_alembic_stamp_is_healthy():
    """A fresh database has no stamp, and create_all handles it. Not a repair case."""
    assert _integrity([]) is True
    assert _integrity(["manufacturers", "device_models"]) is True


def test_a_stamped_database_with_its_tables_is_healthy():
    assert _integrity(["alembic_version", "manufacturers", "device_models"]) is True


def test_a_stamp_without_tables_is_the_repair_case():
    """This is the state the repair exists for: migrations recorded, nothing created.

    It is what a container gets when alembic ran against a different database file
    from the one the app opens -- the exact failure the DATABASE_URL change to
    alembic/env.py prevents.
    """
    assert _integrity(["alembic_version"]) is False


def test_a_partially_created_database_is_also_repaired():
    """Half the schema is not healthy, even though one expected table is present."""
    assert _integrity(["alembic_version", "manufacturers"]) is False
    assert _integrity(["alembic_version", "device_models"]) is False


def test_clearing_the_alembic_stamp_empties_only_that_table():
    """The repair deletes rows from alembic_version, and must not drop it."""
    import sqlalchemy
    from src.database import _clear_alembic_stamp

    engine = sqlalchemy.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sqlalchemy.text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        conn.execute(sqlalchemy.text("INSERT INTO alembic_version VALUES ('abc123')"))
        _clear_alembic_stamp(conn)

        remaining = conn.execute(sqlalchemy.text("SELECT COUNT(*) FROM alembic_version")).scalar()
        assert remaining == 0
        # The table itself survives, so alembic can stamp it again.
        tables = {r[0] for r in conn.execute(
            sqlalchemy.text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}
        assert "alembic_version" in tables


@pytest.mark.asyncio
async def test_a_successful_scrape_is_recorded():
    from sqlalchemy import select
    from src.devices.models import ScrapeRun
    from src.scrapers import service as ss

    async with test_session_maker() as db:
        await ss.record_scrape_run(
            db, "acme", datetime(2026, 9, 12, 10, 0), 12.34,
            {
                "success": True,
                "devices_synced": {"created": 2, "updated": 3, "total": 5},
                "new_firmware_versions": 7,
                "notifications_created": 1,
                "devices_without_firmware": ["Quiet Box"],
                "devices_failed": [],
                "devices_not_checked": [],
                "identical_pages": [],
            },
        )
        run = (await db.execute(select(ScrapeRun))).scalars().one()

    assert run.scraper_type == "acme"
    assert run.success is True
    assert run.devices_total == 5
    assert run.new_versions == 7
    assert run.devices_without_firmware == 1
    assert run.duration_seconds == 12.34
    assert run.failed_devices is None


@pytest.mark.asyncio
async def test_a_failed_scrape_records_which_devices_failed():
    """Counts answer "was it broken"; the names answer "what went quiet"."""
    from sqlalchemy import select
    from src.devices.models import ScrapeRun
    from src.scrapers import service as ss

    async with test_session_maker() as db:
        await ss.record_scrape_run(
            db, "acme", datetime(2026, 9, 12, 10, 0), 3.0,
            {
                "success": True,
                "devices_synced": {"total": 4},
                "devices_failed": ["MODX6", "MODX7"],
                "identical_pages": [["https://e.invalid/a", "https://e.invalid/b"]],
            },
        )
        run = (await db.execute(select(ScrapeRun))).scalars().one()

    assert run.devices_failed == 2
    assert json.loads(run.failed_devices) == ["MODX6", "MODX7"]
    # A URL shape that stopped selecting is recorded too, since it looks like an
    # absence in the firmware history rather than a fault.
    assert run.identical_page_groups == 1


@pytest.mark.asyncio
async def test_an_unknown_scraper_still_produces_a_run():
    """A scrape that never started is itself a fact about that day."""
    from sqlalchemy import select
    from src.devices.models import ScrapeRun
    from src.scrapers import service as ss

    async with test_session_maker() as db:
        result = await ss.scrape_manufacturer(db, "not-a-real-scraper")
        run = (await db.execute(select(ScrapeRun))).scalars().one()

    assert result["success"] is False
    assert run.success is False
    assert "not-a-real-scraper" in run.error


@pytest.mark.asyncio
async def test_a_dead_device_list_still_produces_a_run():
    """The most total failure was the one that left no trace.

    A vendor whose product index starts 500ing never reaches the firmware loop, so the
    scrape returned early and wrote nothing. That reads as reassuring and is the
    opposite: /scrape-status shows the newest run per vendor, and a run that was never
    written cannot be the newest, so the vendor kept displaying its last successful run
    indefinitely.

    devices_total is 0 here rather than absent, which is the honest number -- no device
    list means nothing was checked, as distinct from a run that checked devices and
    found nothing.
    """
    from sqlalchemy import select
    from src.devices.models import ScrapeRun
    from src.scrapers.base import BaseScraper, ScraperResult
    from src.scrapers.registry import ScraperRegistry
    from src.scrapers import service as ss

    class _DeadIndex(BaseScraper):
        manufacturer_name = "Dead Index Audio"
        manufacturer_slug = "deadindex"
        manufacturer_website = "https://dead.example"

        async def fetch_device_list(self) -> ScraperResult:
            return ScraperResult(success=False, error="index page returned 500")

        async def fetch_firmware_versions(self, device_name, firmware_page_url) -> ScraperResult:
            return ScraperResult(success=True, firmware_versions=[])

    ScraperRegistry.register(_DeadIndex)
    try:
        async with test_session_maker() as db:
            result = await ss.scrape_manufacturer(db, "deadindex")
            run = (await db.execute(select(ScrapeRun))).scalars().one()
    finally:
        ScraperRegistry._scrapers.pop("deadindex", None)

    assert result["success"] is False
    assert run.success is False
    assert "500" in run.error
    assert run.devices_total == 0
    # Attributed to the vendor, which ensure_manufacturer created before the failure.
    assert run.manufacturer_id is not None


@pytest.mark.asyncio
async def test_recording_a_run_never_breaks_the_scrape(monkeypatch):
    """The row is diagnostic; losing it must not lose the result it describes."""
    from src.scrapers import service as ss

    async with test_session_maker() as db:
        async def explode():
            raise RuntimeError("database went away")

        monkeypatch.setattr(db, "commit", explode)
        # Must not raise.
        await ss.record_scrape_run(db, "acme", datetime(2026, 9, 12), 1.0, {"success": True})


@pytest.mark.asyncio
async def test_scrape_runs_can_be_read_back(client):
    from src.scrapers import service as ss

    async with test_session_maker() as db:
        await ss.record_scrape_run(
            db, "acme", datetime(2026, 9, 12, 10, 0), 2.0,
            {"success": True, "devices_synced": {"total": 3}, "new_firmware_versions": 4},
        )
        await ss.record_scrape_run(
            db, "other", datetime(2026, 9, 12, 11, 0), 1.0,
            {"success": False, "error": "boom", "devices_failed": ["Thing"]},
        )

    everything = (await client.get("/api/firmware/runs")).json()
    assert {r["scraper_type"] for r in everything} == {"acme", "other"}

    only_acme = (await client.get("/api/firmware/runs?scraper_type=acme")).json()
    assert len(only_acme) == 1
    assert only_acme[0]["new_versions"] == 4
    assert only_acme[0]["failed_devices"] == []


def test_backup_script_round_trips_through_a_sql_dump(tmp_path):
    """The dump has to reproduce the database, not merely parse.

    It also has to restore over an existing file. Replaying a dump into a database
    that still has rows merges into it and fails on the first duplicate key, which
    leaves a half-restored mess where a backup was supposed to be.
    """
    import shutil
    import sqlite3 as sq
    import subprocess

    script = Path(__file__).parent.parent / "scripts" / "backup_db.sh"
    shutil.copy(script, tmp_path / "backup_db.sh")
    (tmp_path / "scripts").mkdir(exist_ok=True)

    db = tmp_path / "firmware_tracker.db"
    with sq.connect(db) as conn:
        conn.execute("CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT)")
        conn.executemany("INSERT INTO widgets VALUES (?, ?)", [(1, "one"), (2, "two")])

    def run(*args):
        return subprocess.run(["bash", str(script), *args], cwd=tmp_path,
                              capture_output=True, text=True)

    assert run().returncode == 0
    dumps = list((tmp_path / "backups").glob("*.sql"))
    assert len(dumps) == 1, "a backup should produce a .sql alongside the .db"
    assert "INSERT INTO widgets" in dumps[0].read_text()

    # Change the database, then restore the dump over the top of it.
    with sq.connect(db) as conn:
        conn.execute("INSERT INTO widgets VALUES (3, 'three')")

    result = run("restore", str(dumps[0]))
    assert result.returncode == 0, result.stderr

    with sq.connect(db) as conn:
        rows = conn.execute("SELECT id, name FROM widgets ORDER BY id").fetchall()

    # Back to the snapshot exactly: the row added afterwards is gone, not merged.
    assert rows == [(1, "one"), (2, "two")]


async def _seed_a_family():
    """A manufacturer with one model, two firmware versions, a device and a notification."""
    from src.devices import service as ds
    from src.devices.models import DeviceCategory
    from src.devices.schemas import (
        DeviceModelCreate, FirmwareVersionCreate, ManufacturerCreate,
        MyDeviceCreate, NotificationCreate,
    )

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(
            db, ManufacturerCreate(name="Cascade Co", slug="cascadeco")
        )
        model = await ds.create_device_model(db, DeviceModelCreate(
            manufacturer_id=mfr.id, name="Cascade One", category=DeviceCategory.OTHER,
        ))
        old = await ds.create_firmware_version(db, FirmwareVersionCreate(
            device_model_id=model.id, version="1.0.0", is_latest=False,
        ))
        new = await ds.create_firmware_version(db, FirmwareVersionCreate(
            device_model_id=model.id, version="2.0.0", is_latest=True,
        ))
        mine = await ds.create_my_device(db, MyDeviceCreate(device_model_id=model.id))
        await ds.create_notification(db, NotificationCreate(
            my_device_id=mine.id, firmware_version_id=new.id, title="New firmware",
        ))
        return mfr.id, model.id, mine.id, (old.id, new.id)


async def _row_counts():
    from sqlalchemy import func, select as sa_select

    from src.devices.models import (
        DeviceModel, FirmwareVersion, Manufacturer, MyDevice, Notification,
    )

    async with test_session_maker() as db:
        counts = {}
        for label, model in (
            ("manufacturers", Manufacturer), ("models", DeviceModel),
            ("firmware", FirmwareVersion), ("my_devices", MyDevice),
            ("notifications", Notification),
        ):
            counts[label] = (
                await db.execute(sa_select(func.count()).select_from(model))
            ).scalar_one()
        return counts


@pytest.mark.asyncio
async def test_deleting_a_device_model_takes_its_firmware_with_it():
    """The orphans this fixes: firmware rows pointing at an id that no longer exists."""
    from src.devices import service as ds

    _mfr_id, model_id, _mine_id, _fw = await _seed_a_family()
    assert (await _row_counts())["firmware"] == 2

    async with test_session_maker() as db:
        assert await ds.delete_device_model(db, model_id) is True

    counts = await _row_counts()
    assert counts["models"] == 0
    assert counts["firmware"] == 0, "firmware rows outlived their device model"
    assert counts["my_devices"] == 0
    assert counts["notifications"] == 0
    assert counts["manufacturers"] == 1, "the manufacturer should survive"


@pytest.mark.asyncio
async def test_deleting_a_manufacturer_cascades_the_whole_way_down():
    """manufacturer -> models -> firmware -> notifications, and -> my devices."""
    from src.devices import service as ds

    mfr_id, _model_id, _mine_id, _fw = await _seed_a_family()

    async with test_session_maker() as db:
        assert await ds.delete_manufacturer(db, mfr_id) is True

    assert await _row_counts() == {
        "manufacturers": 0, "models": 0, "firmware": 0,
        "my_devices": 0, "notifications": 0,
    }


@pytest.mark.asyncio
async def test_deleting_a_tracked_device_takes_its_notifications():
    """Notifications point at a my_device, and untracking is the common delete."""
    from src.devices import service as ds

    _mfr_id, _model_id, mine_id, _fw = await _seed_a_family()

    async with test_session_maker() as db:
        assert await ds.delete_my_device(db, mine_id) is True

    counts = await _row_counts()
    assert counts["my_devices"] == 0
    assert counts["notifications"] == 0, "notifications outlived the device"
    # The catalogue itself is untouched: untracking a device is not deleting it.
    assert counts["models"] == 1
    assert counts["firmware"] == 2


@pytest.mark.asyncio
async def test_deleting_something_that_is_not_there_reports_false():
    """The bulk-delete version returned rowcount > 0; the ORM version has to say so itself."""
    from src.devices import service as ds

    async with test_session_maker() as db:
        assert await ds.delete_manufacturer(db, 9999) is False
        assert await ds.delete_device_model(db, 9999) is False
        assert await ds.delete_my_device(db, 9999) is False


@pytest.mark.asyncio
async def test_sqlite_is_told_to_enforce_foreign_keys():
    """Off by default, and off means a stranded row is written without complaint.

    Asserted against a connection rather than the source, because the pragma is
    per-connection: setting it once on the engine that ran a migration proves
    nothing about the one serving requests.
    """
    from sqlalchemy import text as sa_text

    async with test_engine.connect() as conn:
        assert (await conn.execute(sa_text("PRAGMA foreign_keys"))).scalar_one() == 1
