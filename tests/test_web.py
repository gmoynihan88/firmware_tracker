import os
from datetime import datetime
import time

import pytest

from tests.support import _seed_notification, _seed_unversioned, test_session_maker


@pytest.mark.asyncio
async def test_dashboard_separates_unknown_firmware_from_updates(client):
    """A device with no recorded installed version is unknown, not behind.

    The dashboard previously fell through to "Update Available" whenever a latest
    version existed, which is a guess: 10 of 11 unrecorded devices were shown as
    needing an update.
    """
    from src.devices.schemas import (
        DeviceModelCreate, FirmwareVersionCreate, ManufacturerCreate, MyDeviceCreate,
    )
    from src.devices import service as ds
    from src.devices.models import DeviceCategory

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(db, ManufacturerCreate(name="DashCo", slug="dashco"))

        async def _tracked(name, installed):
            model = await ds.create_device_model(db, DeviceModelCreate(
                manufacturer_id=mfr.id, name=name, category=DeviceCategory.OTHER,
            ))
            await ds.create_firmware_version(db, FirmwareVersionCreate(
                device_model_id=model.id, version="2.0.6", is_latest=True,
            ))
            await ds.create_my_device(db, MyDeviceCreate(
                device_model_id=model.id, current_firmware_version=installed,
                notify_on_update=True,
            ))

        await _tracked("No Version Recorded", None)
        await _tracked("Behind", "2.0.5")
        await _tracked("Up To Date", "2.0.6")

    response = await client.get("/")
    assert response.status_code == 200
    html = response.text

    assert html.count('data-status="unknown"') == 1
    assert html.count('data-status="update"') == 1
    assert html.count('data-status="current"') == 1
    # And the filter offers the new state.
    assert "Firmware Unknown" in html


@pytest.mark.asyncio
async def test_dashboard_does_not_flag_a_device_running_ahead(client):
    """Installed newer than published is current, not an update.

    The old check used !=, so a hotfix that never reached the vendor's list read as
    an update being available.
    """
    from src.devices.schemas import (
        DeviceModelCreate, FirmwareVersionCreate, ManufacturerCreate, MyDeviceCreate,
    )
    from src.devices import service as ds
    from src.devices.models import DeviceCategory

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(db, ManufacturerCreate(name="AheadCo", slug="aheadco"))
        model = await ds.create_device_model(db, DeviceModelCreate(
            manufacturer_id=mfr.id, name="Ahead Synth", category=DeviceCategory.SYNTHESIZER,
        ))
        await ds.create_firmware_version(db, FirmwareVersionCreate(
            device_model_id=model.id, version="1.7.0", is_latest=True,
        ))
        await ds.create_my_device(db, MyDeviceCreate(
            device_model_id=model.id, current_firmware_version="1.7.1", notify_on_update=True,
        ))

    html = (await client.get("/")).text
    assert html.count('data-status="current"') == 1
    assert 'data-status="update"' not in html


@pytest.mark.asyncio
async def test_dashboard_renders_a_table_with_the_expected_columns(client):
    """One row per device, dense enough to scan 71 of them."""
    from src.devices.schemas import (
        DeviceModelCreate, FirmwareVersionCreate, ManufacturerCreate, MyDeviceCreate,
    )
    from src.devices import service as ds
    from src.devices.models import DeviceCategory

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(db, ManufacturerCreate(name="TableCo", slug="tableco"))
        model = await ds.create_device_model(db, DeviceModelCreate(
            manufacturer_id=mfr.id, name="Table Synth", category=DeviceCategory.SYNTHESIZER,
        ))
        await ds.create_firmware_version(db, FirmwareVersionCreate(
            device_model_id=model.id, version="2.0.6", is_latest=True,
        ))
        await ds.create_my_device(db, MyDeviceCreate(
            device_model_id=model.id, current_firmware_version="2.0.5", notify_on_update=True,
        ))

    html = (await client.get("/")).text

    for column in ("Vendor", "Product", "Category", "Installed", "Latest", "Status"):
        assert f">{column}<" in html, column

    assert html.count('class="device-row') == 1
    assert "TableCo" in html
    assert "2.0.5" in html and "2.0.6" in html
    # The row still carries the filter attributes.
    assert 'data-status="update"' in html
    assert 'data-brand="tableco"' in html


@pytest.mark.asyncio
async def test_dashboard_row_links_to_the_device_detail_page(client):
    from src.devices.schemas import (
        DeviceModelCreate, ManufacturerCreate, MyDeviceCreate,
    )
    from src.devices import service as ds
    from src.devices.models import DeviceCategory

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(db, ManufacturerCreate(name="LinkCo", slug="linkco"))
        model = await ds.create_device_model(db, DeviceModelCreate(
            manufacturer_id=mfr.id, name="Link Pedal", category=DeviceCategory.GUITAR_PEDAL,
        ))
        device = await ds.create_my_device(db, MyDeviceCreate(device_model_id=model.id))

    html = (await client.get("/")).text
    assert f'href="/devices/{device.id}"' in html


@pytest.mark.asyncio
async def test_dashboard_filter_chips_are_alphabetical(client):
    """Seventeen brands in insertion order is a list you have to read twice.

    Status is deliberately left in severity order rather than alphabetised.
    """
    import re

    from src.devices.schemas import DeviceModelCreate, ManufacturerCreate, MyDeviceCreate
    from src.devices import service as ds
    from src.devices.models import DeviceCategory

    async with test_session_maker() as db:
        # Created deliberately out of alphabetical order.
        for name, slug in (("Zeta Audio", "zeta"), ("Alpha Audio", "alpha"), ("Mid Audio", "mid")):
            mfr = await ds.create_manufacturer(db, ManufacturerCreate(name=name, slug=slug))
            model = await ds.create_device_model(db, DeviceModelCreate(
                manufacturer_id=mfr.id, name=f"{name} Box", category=DeviceCategory.OTHER,
            ))
            await ds.create_my_device(db, MyDeviceCreate(device_model_id=model.id))

    html = (await client.get("/")).text

    def chip_labels(group_id: str) -> list:
        """Chip text, past the drawn checkbox element that precedes it."""
        block = re.search(rf'id="{group_id}"(.*?)</div>', html, re.S).group(1)
        return [label.strip() for label in re.findall(r'</span>([^<]+)</span>', block)]

    assert chip_labels("brand-filters") == ["Alpha Audio", "Mid Audio", "Zeta Audio"]

    categories = chip_labels("category-filters")
    assert categories and categories == sorted(categories)


@pytest.mark.asyncio
async def test_dashboard_shows_when_the_latest_firmware_was_released(client):
    """The vendor's release date, which is what "is this recent?" actually asks.

    This column used to show the discovery date -- when a scrape first recorded the
    version. That was the best available when half the catalogue had no release date;
    66 of the 71 tracked devices with a latest version now have one, so the weaker
    signal was taking the column.
    """
    from datetime import datetime

    from src.devices.schemas import (
        DeviceModelCreate, FirmwareVersionCreate, ManufacturerCreate, MyDeviceCreate,
    )
    from src.devices import service as ds
    from src.devices.models import DeviceCategory

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(db, ManufacturerCreate(name="DateCo", slug="dateco"))
        model = await ds.create_device_model(db, DeviceModelCreate(
            manufacturer_id=mfr.id, name="Dated Synth", category=DeviceCategory.SYNTHESIZER,
        ))
        await ds.create_firmware_version(db, FirmwareVersionCreate(
            device_model_id=model.id, version="1.2.0", is_latest=True,
            release_date=datetime(2025, 4, 17),
        ))
        await ds.create_my_device(db, MyDeviceCreate(device_model_id=model.id))

    html = (await client.get("/")).text

    assert ">Released<" in html
    assert "2025-04-17" in html


async def _seed_one_device(name: str = "Filter Box", slug: str = "filterco"):
    """The dashboard renders no filter bars when nothing is tracked."""
    from src.devices.schemas import DeviceModelCreate, ManufacturerCreate, MyDeviceCreate
    from src.devices import service as ds
    from src.devices.models import DeviceCategory

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(db, ManufacturerCreate(name=name, slug=slug))
        model = await ds.create_device_model(db, DeviceModelCreate(
            manufacturer_id=mfr.id, name=f"{name} One", category=DeviceCategory.OTHER,
        ))
        await ds.create_my_device(db, MyDeviceCreate(device_model_id=model.id))


@pytest.mark.asyncio
async def test_status_filter_comes_first(client):
    """Status is the filter people reach for, so it leads.

    Then brand, then device type.
    """
    import re

    await _seed_one_device()
    html = (await client.get("/")).text
    order = re.findall(r'id="(status|brand|category)-filters"', html)

    assert order == ["status", "brand", "category"]


@pytest.mark.asyncio
async def test_every_filter_chip_draws_a_checkbox(client):
    """The native input is hidden, so the chip has to show the state itself.

    Colour alone is not enough: the table already uses colour for "update
    available", so a coloured chip read as a warning rather than a selection.
    """
    import re

    await _seed_one_device()
    html = (await client.get("/")).text

    chips = re.findall(r'<span class="filter-chip">(.*?)</span>\s*</label>', html, re.S)
    assert chips, "expected filter chips"
    assert all('<span class="chip-box"></span>' in chip for chip in chips)


def test_asset_version_tracks_file_contents(tmp_path, monkeypatch):
    """The version must change when the file does, without a restart.

    uvicorn's reloader only watches Python files, so a version captured at import
    would go stale exactly when a stylesheet is being edited.
    """
    from src import templating

    stylesheet = tmp_path / "css"
    stylesheet.mkdir()
    target = stylesheet / "style.css"
    target.write_text("body { color: red }")

    monkeypatch.setattr(templating.settings, "static_dir", tmp_path)

    first = templating.asset_version("css/style.css")
    assert first == templating.asset_version("css/style.css")   # stable while unchanged

    # Rewrite with different contents and a different mtime.
    import os
    import time

    target.write_text("body { color: blue }")
    os.utime(target, (time.time() + 2, time.time() + 2))

    assert templating.asset_version("css/style.css") != first


def test_asset_version_survives_a_missing_file():
    """A missing asset must not break rendering the page."""
    from src.templating import asset_version

    assert asset_version("css/does-not-exist.css") == "0"


@pytest.mark.asyncio
async def test_stylesheet_link_is_content_versioned(client):
    """The link used to carry a hand-written ?v=6 that nobody remembered to bump."""
    import re

    html = (await client.get("/")).text
    links = re.findall(r'/static/css/([a-z]+)\.css\?v=([a-f0-9]+)', html)

    # One link per stylesheet, in cascade order, each carrying its own content hash.
    assert [name for name, _ in links] == [
        "base", "nav", "components", "dashboard", "device", "notifications", "catalog", "login", "responsive",
    ]
    assert all(len(version) >= 8 for _, version in links), "expected content hashes, not hand-set numbers"


@pytest.mark.asyncio
async def test_static_assets_are_cacheable(client):
    """Safe to cache hard only because the URL changes when the file does."""
    response = await client.get("/static/css/base.css")

    assert response.status_code == 200
    assert "max-age=31536000" in response.headers["cache-control"]
    assert "immutable" in response.headers["cache-control"]


@pytest.mark.asyncio
async def test_every_page_renders(client):
    """A template that references a variable the route stopped passing returns 500."""
    await _seed_one_device()

    for path in ("/", "/catalog", "/notifications", "/devices/add"):
        response = await client.get(path)
        assert response.status_code == 200, f"{path} -> {response.status_code}"
        assert response.text.strip(), f"{path} rendered empty"

    # The badge is the exception and renders nothing at all when there is nothing
    # unread, because HTMX swaps the response in and an empty one clears the badge.
    badge = await client.get("/partials/notification-badge")
    assert badge.status_code == 200
    assert badge.text.strip() == ""


@pytest.mark.asyncio
async def test_adding_a_device_through_the_form(client):
    from src.devices import service as ds
    from src.devices.models import DeviceCategory
    from src.devices.schemas import DeviceModelCreate, ManufacturerCreate

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(db, ManufacturerCreate(name="Form Co", slug="formco"))
        model = await ds.create_device_model(db, DeviceModelCreate(
            manufacturer_id=mfr.id, name="Form Box", category=DeviceCategory.OTHER,
        ))
        model_id = model.id

    response = await client.post("/devices/add", data={
        "device_model_id": str(model_id),
        "nickname": "Bench unit",
        "current_firmware_version": "1.2.3",
        "notes": "",
    }, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"

    mine = (await client.get("/api/my-devices")).json()
    assert len(mine) == 1
    assert mine[0]["nickname"] == "Bench unit"
    # An empty optional field becomes NULL rather than an empty string.
    assert mine[0]["notes"] is None


@pytest.mark.asyncio
async def test_adding_a_device_for_a_model_that_does_not_exist_is_404(client):
    response = await client.post("/devices/add", data={"device_model_id": "9999"},
                                 follow_redirects=False)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_edit_and_delete_a_device_through_the_form(client):
    await _seed_one_device(name="Editable", slug="editco")
    device_id = (await client.get("/api/my-devices")).json()[0]["id"]

    assert (await client.get(f"/devices/{device_id}")).status_code == 200
    assert (await client.get(f"/devices/{device_id}/edit")).status_code == 200

    edited = await client.post(f"/devices/{device_id}/edit", data={
        "nickname": "Renamed", "current_firmware_version": "9.9.9", "notes": "",
    }, follow_redirects=False)
    assert edited.status_code == 303
    assert edited.headers["location"] == f"/devices/{device_id}"

    detail = (await client.get(f"/api/my-devices/{device_id}")).json()
    assert detail["nickname"] == "Renamed"
    assert detail["current_firmware_version"] == "9.9.9"
    # The edit form defaults notify_on_update to False when the box is unticked.
    assert detail["notify_on_update"] is False

    deleted = await client.post(f"/devices/{device_id}/delete", follow_redirects=False)
    assert deleted.status_code == 303
    assert deleted.headers["location"] == "/"
    assert (await client.get(f"/api/my-devices/{device_id}")).status_code == 404


@pytest.mark.asyncio
async def test_web_routes_404_on_missing_devices(client):
    for path in ("/devices/9999", "/devices/9999/edit"):
        assert (await client.get(path)).status_code == 404, path
    for path in ("/devices/9999/edit", "/devices/9999/delete"):
        assert (await client.post(path, data={}, follow_redirects=False)).status_code == 404, path


@pytest.mark.asyncio
async def test_notification_badge_partial_tracks_the_count(client):
    before = await client.get("/partials/notification-badge")
    assert before.status_code == 200

    note_id = await _seed_notification(slug="badgeco")
    during = await client.get("/partials/notification-badge")
    assert "1" in during.text

    await client.post(f"/notifications/{note_id}/read", follow_redirects=False)
    after = await client.get("/partials/notification-badge")
    assert after.status_code == 200


@pytest.mark.asyncio
async def test_notification_pages_mark_read(client):
    note_id = await _seed_notification(slug="pageco")

    assert (await client.get("/notifications")).status_code == 200
    assert (await client.get("/api/notifications/count")).json()["unread_count"] == 1

    marked = await client.post(f"/notifications/{note_id}/read", follow_redirects=False)
    assert marked.status_code in (200, 303)
    assert (await client.get("/api/notifications/count")).json()["unread_count"] == 0

    await _seed_notification(slug="pageco2")
    await client.post("/notifications/read-all", follow_redirects=False)
    assert (await client.get("/api/notifications/count")).json()["unread_count"] == 0


@pytest.mark.asyncio
async def test_device_models_partial_filters_by_manufacturer(client):
    from src.devices import service as ds
    from src.devices.models import DeviceCategory
    from src.devices.schemas import DeviceModelCreate, ManufacturerCreate

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(db, ManufacturerCreate(name="Partial Co", slug="partialco"))
        await ds.create_device_model(db, DeviceModelCreate(
            manufacturer_id=mfr.id, name="Partial Box", category=DeviceCategory.OTHER,
        ))
        mfr_id = mfr.id

    response = await client.get(f"/partials/device-models?manufacturer_id={mfr_id}")
    assert response.status_code == 200
    assert "Partial Box" in response.text


@pytest.mark.asyncio
async def test_vendor_cards_use_the_vendor_s_own_spelling(client):
    """The template used to title-case the registry slug.

    That renders "Ikmultimedia", "Izotope", "Line6" and "Nativeinstruments" -- four
    of twenty-three vendors misspelled on the page a user browses. Each scraper
    already carries the real name, so the route passes it.
    """
    html = (await client.get("/catalog")).text

    assert ">IK Multimedia<" in html
    assert ">iZotope<" in html
    assert ">Line 6<" in html
    assert ">Native Instruments<" in html
    assert "Ikmultimedia" not in html
    assert "Nativeinstruments" not in html


@pytest.mark.asyncio
async def test_vendor_card_falls_back_to_last_scraped_at(client):
    """scrape_runs only goes back to the day that table was added.

    Twenty of twenty-three vendors have no row in it, and reading the card as
    "never scraped" for those is a worse claim than the gap it describes --
    manufacturers.last_scraped_at has been maintained since the beginning.
    """
    from datetime import datetime
    from sqlalchemy import update

    from src.devices.models import Manufacturer
    from src.devices.schemas import ManufacturerCreate
    from src.devices import service as ds

    async with test_session_maker() as db:
        await ds.create_manufacturer(db, ManufacturerCreate(name="Boss", slug="boss"))
        await db.execute(
            update(Manufacturer)
            .where(Manufacturer.slug == "boss")
            .values(last_scraped_at=datetime(2026, 3, 4))
        )
        await db.commit()

    html = (await client.get("/catalog")).text

    assert "scraped 4 Mar" in html


@pytest.mark.asyncio
async def test_catalog_marks_devices_the_user_already_tracks(client):
    """Offering to Track something already tracked adds a second copy of it."""
    import re

    await _seed_one_device(name="Filter Box", slug="filterco")
    html = (await client.get("/catalog")).text

    row = re.search(r"<tr[^>]*>(?:(?!</tr>).)*Filter Box One.*?</tr>", html, re.S)
    assert row, "the seeded device is missing from the table"
    assert "tracked" in row.group(0)
    assert ">Track<" not in row.group(0)


@pytest.mark.asyncio
async def test_catalog_shows_the_latest_version_per_device(client):
    """One query for the whole table rather than one per row."""
    import re

    from src.devices.schemas import (
        DeviceModelCreate, FirmwareVersionCreate, ManufacturerCreate,
    )
    from src.devices.models import DeviceCategory
    from src.devices import service as ds

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(
            db, ManufacturerCreate(name="Verso", slug="verso")
        )
        model = await ds.create_device_model(db, DeviceModelCreate(
            manufacturer_id=mfr.id, name="Verso One", category=DeviceCategory.OTHER,
        ))
        await ds.create_firmware_version(db, FirmwareVersionCreate(
            device_model_id=model.id, version="1.0.0", is_latest=False,
        ))
        await ds.create_firmware_version(db, FirmwareVersionCreate(
            device_model_id=model.id, version="2.4.1", is_latest=True,
        ))

    html = (await client.get("/catalog")).text
    row = re.search(r"<tr[^>]*>(?:(?!</tr>).)*Verso One.*?</tr>", html, re.S)

    assert row
    assert "2.4.1" in row.group(0)
    assert "1.0.0" not in row.group(0)


@pytest.mark.asyncio
async def test_notification_timestamps_share_one_column(client):
    """The content block needs flex:1 or it shrinks to its own text.

    Without it every card's title starts at a different x and the timestamps form
    a ragged edge down the page, because space-between has no free space to
    distribute inside a shrink-to-fit box.
    """
    css = (await client.get("/static/css/notifications.css")).text
    block = css.split(".notification-content {", 1)[1].split("}", 1)[0]

    assert "flex: 1" in block
    assert "min-width: 0" in block


@pytest.mark.asyncio
async def test_catalog_shows_the_vendor_s_release_date(client):
    """The Released column carries the vendor's date and nothing else.

    Two thirds of the current versions have one. For the rest the vendor publishes
    none, and `created_at` -- when this tracker first saw the version -- is a
    different fact. Borrowing it under a "Released" heading would turn "we started
    looking in September" into "the vendor shipped this in September", which is the
    invention the scrapers are written to avoid. The dashboard shows first-seen in
    its own Discovered column.
    """
    import re
    from datetime import datetime

    from sqlalchemy import update

    from src.devices.models import DeviceCategory, FirmwareVersion
    from src.devices.schemas import (
        DeviceModelCreate, FirmwareVersionCreate, ManufacturerCreate,
    )
    from src.devices import service as ds

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(
            db, ManufacturerCreate(name="Datever", slug="datever")
        )
        dated = await ds.create_device_model(db, DeviceModelCreate(
            manufacturer_id=mfr.id, name="Dated Box", category=DeviceCategory.OTHER,
        ))
        undated = await ds.create_device_model(db, DeviceModelCreate(
            manufacturer_id=mfr.id, name="Undated Box", category=DeviceCategory.OTHER,
        ))
        await ds.create_firmware_version(db, FirmwareVersionCreate(
            device_model_id=dated.id, version="3.1.0",
            release_date=datetime(2024, 11, 19), is_latest=True,
        ))
        fw = await ds.create_firmware_version(db, FirmwareVersionCreate(
            device_model_id=undated.id, version="4.0.0", is_latest=True,
        ))
        # Give it a first-seen date that would be visible if the column fell back.
        await db.execute(
            update(FirmwareVersion)
            .where(FirmwareVersion.id == fw.id)
            .values(created_at=datetime(2026, 1, 2))
        )
        await db.commit()

    html = (await client.get("/catalog")).text

    headers = re.findall(r"<th[^>]*>(?:<span[^>]*>)?([A-Za-z]+)", html)
    assert headers[:6] == ["Vendor", "Product", "Type", "Latest", "Other", "Released"]

    dated_row = re.search(r"<tr[^>]*>(?:(?!</tr>).)*Dated Box.*?</tr>", html, re.S)
    assert dated_row and "2024-11-19" in dated_row.group(0)

    undated_row = re.search(r"<tr[^>]*>(?:(?!</tr>).)*Undated Box.*?</tr>", html, re.S)
    assert undated_row
    assert "2026-01-02" not in undated_row.group(0), "fell back to the first-seen date"
    assert "&#8212;" in undated_row.group(0) or "—" in undated_row.group(0)


@pytest.mark.asyncio
async def test_catalog_says_why_there_is_no_version(client):
    """Each reason reads as itself rather than all three as an em-dash."""
    import re

    from src.devices.models import FirmwareAvailability

    await _seed_unversioned("Silent", "silentco", FirmwareAvailability.NOT_PUBLISHED)
    await _seed_unversioned("Analogue", "analogueco", FirmwareAvailability.NO_FIRMWARE)
    await _seed_unversioned("Unchecked", "uncheckedco", None)

    html = (await client.get("/catalog")).text

    def cell(product):
        row = re.search(rf"<tr[^>]*>(?:(?!</tr>).)*{product}.*?</tr>", html, re.S)
        assert row, f"{product} missing from the table"
        return row.group(0)

    assert "not published" in cell("Silent Box")
    assert "no firmware" in cell("Analogue Box")
    # Unexamined stays an em-dash: the field records findings, not guesses.
    assert "not published" not in cell("Unchecked Box")
    assert "no firmware" not in cell("Unchecked Box")


async def _seed_one_of_each():
    from src.devices import service as ds
    from src.devices.models import DeviceCategory
    from src.devices.schemas import DeviceModelCreate, ManufacturerCreate, MyDeviceCreate

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(
            db, ManufacturerCreate(name="Kindco", slug="kindco")
        )
        for name, category in (
            ("Kind Pedal", DeviceCategory.GUITAR_PEDAL),
            ("Kind Synth", DeviceCategory.SYNTHESIZER),
            ("Kind Interface", DeviceCategory.AUDIO_INTERFACE),
            ("Kind Controller", DeviceCategory.MIDI_CONTROLLER),
            ("Kind Other", DeviceCategory.OTHER),
            ("Kind Plugin", DeviceCategory.VST_PLUGIN),
        ):
            model = await ds.create_device_model(db, DeviceModelCreate(
                manufacturer_id=mfr.id, name=name, category=category,
            ))
            await ds.create_my_device(db, MyDeviceCreate(device_model_id=model.id))


def _kinds_by_product(html):
    import re

    found = {}
    for row in re.findall(r"<tr[^>]*data-kind=[^>]*>.*?</tr>", html, re.S):
        kind = re.search(r'data-kind="(\w+)"', row)
        name = re.search(r"Kind \w+", row)
        if kind and name:
            found[name.group(0)] = kind.group(1)
    return found


@pytest.mark.asyncio
async def test_catalog_marks_every_row_hardware_or_software(client):
    """Only VST_PLUGIN is software. Every other category is a physical thing."""
    await _seed_one_of_each()

    kinds = _kinds_by_product((await client.get("/catalog")).text)

    assert kinds == {
        "Kind Pedal": "hardware",
        "Kind Synth": "hardware",
        "Kind Interface": "hardware",
        "Kind Controller": "hardware",
        "Kind Other": "hardware",
        "Kind Plugin": "software",
    }


@pytest.mark.asyncio
async def test_dashboard_marks_every_row_hardware_or_software(client):
    """The same split on the page showing only what you own."""
    await _seed_one_of_each()

    kinds = _kinds_by_product((await client.get("/")).text)

    assert set(kinds.values()) == {"hardware", "software"}
    assert kinds["Kind Plugin"] == "software"
    assert sum(1 for k in kinds.values() if k == "hardware") == 5


@pytest.mark.asyncio
async def test_both_pages_offer_the_type_filter(client):
    """The chips have to exist, or data-kind is dead weight."""
    await _seed_one_of_each()

    for path, container in (("/catalog", "catalog-kind-filters"), ("/", "kind-filters")):
        html = (await client.get(path)).text
        assert f'id="{container}"' in html, f"{path} has no type filter"
        assert 'value="hardware"' in html
        assert 'value="software"' in html


async def _seed_two_vendors():
    from src.devices import service as ds
    from src.devices.models import DeviceCategory
    from src.devices.schemas import DeviceModelCreate, ManufacturerCreate

    async with test_session_maker() as db:
        wanted = await ds.create_manufacturer(
            db, ManufacturerCreate(name="Wanted Co", slug="wantedco")
        )
        other = await ds.create_manufacturer(
            db, ManufacturerCreate(name="Other Co", slug="otherco")
        )
        target = await ds.create_device_model(db, DeviceModelCreate(
            manufacturer_id=wanted.id, name="Target Box",
            category=DeviceCategory.SYNTHESIZER,
        ))
        await ds.create_device_model(db, DeviceModelCreate(
            manufacturer_id=wanted.id, name="Sibling Box",
            category=DeviceCategory.SYNTHESIZER,
        ))
        await ds.create_device_model(db, DeviceModelCreate(
            manufacturer_id=other.id, name="Unrelated Box",
            category=DeviceCategory.SYNTHESIZER,
        ))
        return target.id


@pytest.mark.asyncio
async def test_add_form_preselects_the_model_the_catalogue_sent(client):
    """Both selects, since the model list is useless without its manufacturer."""
    import re

    model_id = await _seed_two_vendors()
    html = (await client.get(f"/devices/add?model_id={model_id}")).text

    manufacturer = re.search(r'<option value="\d+" selected>Wanted Co</option>', html)
    assert manufacturer, "manufacturer not preselected"
    assert re.search(rf'<option value="{model_id}" selected>Target Box', html), \
        "device model not preselected"


@pytest.mark.asyncio
async def test_add_form_lists_only_that_manufacturers_models(client):
    """The page holds every model in the catalogue; the select must not.

    Rendering the lot would put 755 devices in the dropdown, which is the problem
    the Track button exists to avoid.
    """
    import re

    model_id = await _seed_two_vendors()
    html = (await client.get(f"/devices/add?model_id={model_id}")).text

    select = re.search(r'<select[^>]*name="device_model_id".*?</select>', html, re.S).group(0)

    assert "Target Box" in select
    assert "Sibling Box" in select, "dropped the rest of the manufacturer's range"
    assert "Unrelated Box" not in select, "listed another manufacturer's models"


@pytest.mark.asyncio
async def test_add_form_opens_empty_without_a_model_id(client):
    """Reached from the nav rather than the catalogue, nothing is chosen yet."""
    await _seed_two_vendors()
    html = (await client.get("/devices/add")).text

    assert "Select a manufacturer first..." in html
    assert "selected>" not in html


@pytest.mark.asyncio
async def test_add_form_ignores_a_model_id_that_no_longer_exists(client):
    """A stale bookmark must not preselect an id that would fail on submit."""
    await _seed_two_vendors()
    response = await client.get("/devices/add?model_id=999999")

    assert response.status_code == 200
    assert "Select a manufacturer first..." in response.text


@pytest.mark.asyncio
async def test_dashboard_keeps_the_discovery_date_as_a_tooltip(client):
    """Where the vendor publishes no date, the em-dash carries first-seen.

    Putting it in the column would label it a release date, which it is not -- five
    tracked devices are in this state, all from vendors that publish no dates at all.
    The information is still real, so it stays reachable without being mislabelled.
    """
    from datetime import datetime

    from sqlalchemy import update

    from src.devices import service as ds
    from src.devices.models import DeviceCategory, FirmwareVersion
    from src.devices.schemas import (
        DeviceModelCreate, FirmwareVersionCreate, ManufacturerCreate, MyDeviceCreate,
    )

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(
            db, ManufacturerCreate(name="Undated Co", slug="undatedco")
        )
        model = await ds.create_device_model(db, DeviceModelCreate(
            manufacturer_id=mfr.id, name="Undated Synth", category=DeviceCategory.SYNTHESIZER,
        ))
        firmware = await ds.create_firmware_version(db, FirmwareVersionCreate(
            device_model_id=model.id, version="3.0.0", is_latest=True,
        ))
        await db.execute(
            update(FirmwareVersion)
            .where(FirmwareVersion.id == firmware.id)
            .values(created_at=datetime(2026, 2, 11))
        )
        await db.commit()
        await ds.create_my_device(db, MyDeviceCreate(device_model_id=model.id))

    html = (await client.get("/")).text

    assert "First seen by a scrape on 2026-02-11" in html, "lost the discovery date"
    # And it must not be sitting in the column pretending to be a release date.
    assert ">2026-02-11<" not in html


async def _seed_catalog(count, vendor="Pager Co", slug="pagerco", prefix="Unit"):
    from src.devices import service as ds
    from src.devices.models import DeviceCategory
    from src.devices.schemas import DeviceModelCreate, ManufacturerCreate

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(db, ManufacturerCreate(name=vendor, slug=slug))
        for i in range(count):
            await ds.create_device_model(db, DeviceModelCreate(
                manufacturer_id=mfr.id, name=f"{prefix} {i:03d}", category=DeviceCategory.OTHER,
            ))


@pytest.mark.asyncio
async def test_catalog_folds_the_import_panel_away_once_there_are_devices(client):
    """With nothing to browse, importing is the only thing to do, so it starts open."""
    import re

    empty = (await client.get("/catalog")).text
    assert re.search(r'<details class="import-panel"\s+open\s*>', empty)

    await _seed_catalog(1)
    seeded = (await client.get("/catalog")).text
    assert re.search(r'<details class="import-panel"\s*>', seeded)


@pytest.mark.asyncio
async def test_catalog_vendor_chips_live_in_a_dropdown(client):
    import re

    await _seed_catalog(1)
    html = (await client.get("/catalog")).text

    picker = re.search(r'<details class="vendor-picker" id="vendor-picker">(.*?)</details>', html, re.S)
    assert picker, "no vendor dropdown"
    assert 'id="catalog-vendor-filters"' in picker.group(1)
    assert 'value="pagerco"' in picker.group(1)


@pytest.mark.asyncio
async def test_catalog_pager_stays_hidden_without_the_script(client):
    """Every row is on the page until the script pages it; a pager that does nothing is worse than none."""
    import re

    await _seed_catalog(60)
    html = (await client.get("/catalog")).text
    css = (await client.get("/static/css/catalog.css")).text

    assert re.search(r'<nav class="catalog-pager" id="catalog-pager"[^>]*\bhidden\b', html)
    assert html.count('class="catalog-row"') == 60
    # The pager is display:flex, which beats the hidden attribute unless told otherwise.
    assert re.search(r"\.catalog-pager\[hidden\]\s*\{\s*display:\s*none", css)


@pytest.mark.asyncio
async def test_real_chromium_pages_the_catalog(client):
    """Paging, search across pages and sorting, in a browser. Skipped where Chromium is not installed, as in CI."""
    from src.scrapers import base

    if not base.PLAYWRIGHT_AVAILABLE:
        pytest.skip("Playwright not installed")
    from playwright.async_api import async_playwright

    await _seed_catalog(60)
    await _seed_catalog(1, vendor="Zed Co", slug="zedco", prefix="Zulu Needle")
    html = (await client.get("/catalog")).text

    state = """() => ({
        shown: [...document.querySelectorAll('.catalog-row')]
            .filter(r => !r.hidden).map(r => r.children[1].textContent.trim()),
        status: document.getElementById('catalog-pager').hidden
            ? null : document.getElementById('catalog-page-status').textContent,
        prev: document.getElementById('catalog-prev').disabled,
        next: document.getElementById('catalog-next').disabled,
    })"""

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch()
        except Exception as exc:
            pytest.skip(f"Chromium unavailable: {exc}")
        try:
            page = await browser.new_page()
            errors = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            await page.route("**/*", lambda route: route.abort())  # no network, htmx CDN included
            await page.set_content(html)

            first = await page.evaluate(state)
            assert len(first["shown"]) == 50
            assert first["status"] == "1–50 of 61 · page 1 of 2"
            assert first["prev"] and not first["next"]

            await page.click("#catalog-next")
            second = await page.evaluate(state)
            assert len(second["shown"]) == 11
            assert not set(first["shown"]) & set(second["shown"])
            assert second["next"] and not second["prev"]

            # Search reaches every row, not only the current page, and the pager
            # goes away when one page holds the result.
            await page.fill("#catalog-search", "needle")
            found = await page.evaluate(state)
            assert found["shown"] == ["Zulu Needle 000"]
            assert found["status"] is None

            await page.fill("#catalog-search", "")
            assert (await page.evaluate(state))["status"] == "1–50 of 61 · page 1 of 2"

            await page.select_option("#catalog-page-size", "0")
            assert len((await page.evaluate(state))["shown"]) == 61

            # A new order starts from its first page.
            await page.select_option("#catalog-page-size", "25")
            await page.click("#catalog-next")
            await page.click("th[data-column='1']")
            await page.click("th[data-column='1']")
            ordered = await page.evaluate(state)
            assert ordered["shown"][0] == "Zulu Needle 000"
            assert len(ordered["shown"]) == 25
            assert ordered["status"].startswith("1–25 of 61")

            assert errors == []
        finally:
            await browser.close()


async def _seed_history():
    """One product with four versions, one with only its latest, one with none."""
    from datetime import datetime

    from src.devices import service as ds
    from src.devices.models import DeviceCategory
    from src.devices.schemas import DeviceModelCreate, FirmwareVersionCreate, ManufacturerCreate

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(db, ManufacturerCreate(name="History Co", slug="historyco"))
        box, single, _empty = [
            await ds.create_device_model(db, DeviceModelCreate(
                manufacturer_id=mfr.id, name=name, category=DeviceCategory.SYNTHESIZER,
            ))
            for name in ("History Box", "Single Box", "Empty Box")
        ]
        for version, released, notes, latest in (
            ("1.0.0", datetime(2024, 1, 5), "First release.", False),
            ("1.10.0", None, "Fixed <script>alert(1)</script> in the name field.", False),
            ("2.0.0", datetime(2026, 2, 1), "Current release notes.", True),
            ("1.9.0", datetime(2025, 3, 2), None, False),
        ):
            await ds.create_firmware_version(db, FirmwareVersionCreate(
                device_model_id=box.id, version=version, release_date=released,
                changelog_raw=notes, is_latest=latest,
            ))
        await ds.create_firmware_version(db, FirmwareVersionCreate(
            device_model_id=single.id, version="3.0.0", is_latest=True,
        ))
        return box.id


@pytest.mark.asyncio
async def test_catalog_counts_the_versions_behind_the_latest(client):
    import re

    box_id = await _seed_history()
    html = (await client.get("/catalog")).text

    def row(product):
        found = re.search(rf"<tr[^>]*>(?:(?!</tr>).)*{product}.*?</tr>", html, re.S)
        assert found, f"{product} missing from the table"
        return found.group(0)

    history = row("History Box")
    assert f'data-history-url="/catalog/versions/{box_id}"' in history
    assert re.search(r'class="history-link"[^>]*>3</button>', history)

    # Only the latest, or nothing at all: a plain zero with nothing to open.
    for product in ("Single Box", "Empty Box"):
        assert "history-link" not in row(product)
        assert '<span class="muted">0</span>' in row(product)


@pytest.mark.asyncio
async def test_version_history_lists_every_version_but_the_latest(client):
    box_id = await _seed_history()
    response = await client.get(f"/catalog/versions/{box_id}")
    html = response.text

    assert response.status_code == 200
    assert '<h3 id="history-title">History Box</h3>' in html
    assert "History Co &middot; 3 earlier versions" in html
    assert "2.0.0" not in html and "Current release notes." not in html
    # Highest first, as numbers: 1.10.0 is newer than 1.9.0.
    assert html.index("1.10.0") < html.index("1.9.0") < html.index("1.0.0")
    assert "2024-01-05" in html and "First release." in html


@pytest.mark.asyncio
async def test_version_history_escapes_scraped_release_notes(client):
    """Release notes come from vendor pages, and the popup inserts the partial as HTML."""
    box_id = await _seed_history()
    html = (await client.get(f"/catalog/versions/{box_id}")).text

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


@pytest.mark.asyncio
async def test_version_history_of_an_unknown_product_is_a_404(client):
    assert (await client.get("/catalog/versions/999999")).status_code == 404


@pytest.mark.asyncio
async def test_real_chromium_opens_the_version_history(client):
    """Click the count, see the history, close it. Skipped where Chromium is not installed, as in CI."""
    from src.scrapers import base

    if not base.PLAYWRIGHT_AVAILABLE:
        pytest.skip("Playwright not installed")
    from playwright.async_api import async_playwright

    box_id = await _seed_history()
    origin = "http://catalog.test"

    async def serve(route):
        # The app answers its own paths through the test client; nothing else loads.
        url = route.request.url
        if not url.startswith(origin + "/"):
            await route.abort()
            return
        response = await client.get(url[len(origin):])
        await route.fulfill(status=response.status_code, body=response.text,
                           content_type=response.headers.get("content-type", "text/html"))

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch()
        except Exception as exc:
            pytest.skip(f"Chromium unavailable: {exc}")
        try:
            page = await browser.new_page()
            errors = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            await page.route("**/*", serve)
            await page.goto(origin + "/catalog")

            await page.click(f'button[data-history-url="/catalog/versions/{box_id}"]')
            await page.wait_for_selector("#history-dialog[open] .history-row")

            rows = await page.eval_on_selector_all(
                "#history-dialog .history-row",
                "rows => rows.map(r => [...r.children].map(c => c.textContent.trim()))",
            )
            assert [r[0] for r in rows] == ["1.10.0", "1.9.0", "1.0.0"]
            assert rows[0][2] == "Fixed <script>alert(1)</script> in the name field."
            assert rows[1][1:] == ["2025-03-02", "—"]

            await page.click("#history-dialog button:text('Close')")
            assert not await page.evaluate("document.getElementById('history-dialog').open")

            # The backdrop closes it too.
            await page.click(f'button[data-history-url="/catalog/versions/{box_id}"]')
            await page.wait_for_selector("#history-dialog[open] .history-row")
            await page.mouse.click(5, 5)
            assert not await page.evaluate("document.getElementById('history-dialog').open")

            assert errors == []
        finally:
            await browser.close()
