import json

import pytest

from tests.support import _stub_fetch


def _ho_row(name, ids, created, file_name="firmware.zip"):
    return {
        "support_id": abs(hash(name)) % 10000, "support_type_id": 2, "language": 1, "name": name, "is_file": 1,
        "product_type_id": "[18]" if ids else None, "product_id": json.dumps(ids) if ids else None,
        "file": json.dumps({"uid": "vc-upload-1", "name": file_name, "status": "done",
                            "url": f"https://res.hotoneaudio.com/prod/support/{file_name}"}),
        "content": "", "order": 0, "keyword": json.dumps([name]), "pv": 0, "status": 1,
        "created_at": f"{created}T08:28:57.000Z", "updated_at": f"{created}T08:29:50.000Z", "deleted_at": None,
    }


ROWS = [
    _ho_row("Important Notice for Windows 11 Users", [], "2026-07-17"),
    _ho_row("Pulze Mini Firmware V1.1.2(Compatible with Pulze Editor V2.0.2)", [103, 107], "2026-07-21", "Pulze Mini Firmware V1.1.2.zip"),
    _ho_row("Pulze FirmwareV1.4.0 (Compatible with Pulze Editor V2.0.0)", [95], "2025-11-10"),
    _ho_row("Solution of Ampero II Stomp Hardware & Software Connection Problem", [87], "2022-01-21"),
    _ho_row("Pulze Mini FirmwareV1.0.2（Compatible with Pulze App V1.4.4)", [103], "2025-07-18"),
    _ho_row("Ampero Pink Firmware V5.2A & 2020 Limited Edition Firmware V5.2A(Compatible with Ampero Editor V1.5.0)", [83, 72], "2026-03-09"),
    _ho_row("Ampero Firmware V5.2 (Compatible with Ampero Editor V1.5.0)", [1, 90], "2026-03-09"),
    _ho_row("Ampero II Stomp Firmware V2.5.0 (Compatible with Ampero II Software V1.5.1）", [87], "2026-07-30"),
    _ho_row("Ampero II Firmware  V1.1.0 (Compatible with Ampero II Software V1.0.5)", [102], "2024-11-07"),
    _ho_row("Pulze Firmware V1.0.6", [95], "2024-04-12"),
    _ho_row("Pulze Firmware V1.0.8", [95], "2023-11-03"),
    _ho_row("Ampero II Stomp USB Audio Firmware V2.01", [87], "2023-09-05"),
    _ho_row("Ampero One Firmware V1.2SP1（Compatible with Ampero Editor V1.3.0)", [79], "2023-02-09"),
    _ho_row("Ampero One Firmware V1.2 (Compatible with Ampero Editor V1.3.0)", [79], "2021-06-24"),
    _ho_row("Ampero Firmware V4.2A For Ampero Pink Limited Edition (Compatible with Ampero Editor V1.4.2)", [83, 72], "2024-10-28"),
    _ho_row("Ampero Silver Edition Firmware V3.9 (Compatible with Ampero Editor V1.3.1)", [90], "2022-10-08"),
    _ho_row("Ampero Firmware V3.4 (Compatible with Ampero Editor V1.2.6, V1.2.7)", [1], "2019-11-29"),
    _ho_row("Ampero Firmware V3.3B For Pink Limited Edition (Compatible with Ampero Editor V1.2.8)", [72], "2020-08-31"),
    _ho_row("Ampero Firmware V3.2 (Compatible with Ampero Editor V1.2.3, V1.2.4, V1.2.5)", [1], "2019-09-20"),
    _ho_row("Ampero Firmware V3.1 (Compatible with Ampero Editor V1.2.2, V1.2.3)", [1], "2019-09-20"),
    _ho_row("Jogg Firmware with Hotone ASIO Driver support", [27], "2020-07-21"),
    _ho_row("Cybery Firmware Update V1.1.0 for Windows", [25], "2019-12-10"),
    _ho_row("Cybery Firmware Update V1.1.0 for Mac", [25], "2019-12-10"),
]
API_BODY = json.dumps({"code": 200, "message": "成功获取列表", "data": ROWS})


def _dates(versions):
    return [(fw.version, fw.release_date.date().isoformat() if fw.release_date else None) for fw in versions]


def test_hotone_reads_the_firmware_version_not_the_compatible_editors():
    from src.scrapers.plugins.hotone import HotoneScraper

    devices = HotoneScraper()._parse(API_BODY)

    assert [fw.version for fw in devices["Hotone Pulze Mini"]] == ["1.1.2", "1.0.2"]
    assert [fw.version for fw in devices["Hotone Ampero II"]] == ["1.1.0"]
    assert [fw.version for fw in devices["Hotone Ampero One"]] == ["1.2SP1", "1.2"]
    assert [fw.version for fw in devices["Hotone Cybery"]] == ["1.1.0"]


def test_hotone_makes_one_device_of_products_that_share_firmware_and_keeps_the_pink_edition_apart():
    """Ampero and Silver Edition share rows; the Pink Limited Edition's lettered firmware is its own."""
    from src.scrapers.plugins.hotone import HotoneScraper

    devices = HotoneScraper()._parse(API_BODY)

    assert [fw.version for fw in devices["Hotone Ampero"]] == ["5.2", "3.9", "3.4", "3.2", "3.1"]
    assert [fw.version for fw in devices["Hotone Ampero Pink Limited Edition"]] == ["5.2A", "4.2A", "3.3B"]
    assert "Hotone Ampero Silver Edition" not in devices


def test_hotone_skips_notices_unversioned_rows_and_component_firmware():
    """The Stomp's USB Audio Firmware V2.01 is a chip's, not the unit's."""
    from src.scrapers.plugins.hotone import HotoneScraper

    devices = HotoneScraper()._parse(API_BODY)

    assert [fw.version for fw in devices["Hotone Ampero II Stomp"]] == ["2.5.0"]
    assert not [name for name in devices if "Jogg" in name or "Notice" in name or "Solution" in name]


def test_hotone_drops_bulk_upload_days_and_dates_that_contradict_the_version_order():
    """Ampero 3.1 and 3.2 were both posted 2019-09-20; Pulze 1.0.6 was posted after 1.0.8."""
    from src.scrapers.plugins.hotone import HotoneScraper

    devices = HotoneScraper()._parse(API_BODY)

    assert _dates(devices["Hotone Ampero"]) == [("5.2", "2026-03-09"), ("3.9", "2022-10-08"), ("3.4", "2019-11-29"),
                                               ("3.2", None), ("3.1", None)]
    assert _dates(devices["Hotone Pulze"]) == [("1.4.0", "2025-11-10"), ("1.0.8", "2023-11-03"), ("1.0.6", None)]


@pytest.mark.asyncio
async def test_hotone_lists_every_device_from_one_api_call():
    from src.scrapers.plugins.hotone import HotoneScraper as H

    scraper = H()
    asked = _stub_fetch(scraper, {H.API_URL: API_BODY})

    devices = {d.name: d.category for d in (await scraper.fetch_device_list()).devices}
    mini = await scraper.fetch_firmware_versions("Hotone Pulze Mini", H.PAGE_URL)

    assert asked == [H.API_URL]
    assert set(devices.values()) == {"guitar_pedal"}
    assert mini.firmware_versions[0].download_url.endswith("Pulze Mini Firmware V1.1.2.zip")


@pytest.mark.asyncio
async def test_hotone_fails_loudly_without_firmware_rows():
    from src.scrapers.plugins.hotone import HotoneScraper as H

    scraper = H()
    _stub_fetch(scraper, {H.API_URL: json.dumps({"code": 200, "data": [ROWS[0]]})})

    assert (await scraper.fetch_device_list()).success is False
