import json
from datetime import datetime

import pytest

from tests.support import _stub_fetch


def _ej_notes(*lines, bullets=()):
    content = [{"nodeType": "paragraph", "data": {}, "content": [{"nodeType": "text", "value": line, "marks": []}]}
               for line in lines]
    if bullets:
        content.append({"nodeType": "unordered-list", "content": [
            {"nodeType": "list-item", "content": [
                {"nodeType": "paragraph", "content": [{"nodeType": "text", "value": b, "marks": []}]}]}
            for b in bullets]})
    return {"json": {"nodeType": "document", "data": {}, "content": content}}


def _ej_link(title, version, brand=None, product_type=None, usb=True):
    """A hardware unit's link in a release; the history's units carry a title only."""
    unit = {"__typename": "HardwareHardwareUnit", "title": title}
    if brand:
        unit.update(brand=brand, productType=product_type, infoLink=f"https://example.com/{title.lower().replace(' ', '-')}")
    slug = title.replace(" ", "%20")
    link = {"winUrl": f"https://public.inmusiccdn.com/Engine/{version}/RELEASE/x/{slug}%20{version}%20Updater.exe",
            "usbUrl": f"https://public.inmusiccdn.com/Engine/{version}/RELEASE/x/{title.replace(' ', '')}-{version}-Update.img",
            "otaOnly": False, "hardwareUnit": unit}
    if not usb:
        # Only the URL-encoded updater names the version: "%205.1.0" must read as 5.1.0.
        del link["usbUrl"]
        link["winUrl"] = f"https://public.inmusiccdn.com/Engine/RELEASE/x/{slug}%20{version}%20Updater.exe"
    return link


def _ej_release(version, date, links, notes=None):
    return {"__typename": "DownloadsEngineOsRelease", "version": version, "releaseDate": f"{date}T00:00:00.000Z",
            "releaseNotes": notes or _ej_notes("Improvements and Fixes"), "hardwareUnitLinksCollection": {"items": links}}


def _ej_page(os_history, desktop_history=(), summary_links=()):
    data = {"props": {"pageProps": {"page": {"sections": [
        {"__typename": "PageSectionContent"},
        {"__typename": "PageSectionDownloads", "engineDesktopRelease": {"version": "v5.1.0"},
         "engineOsReleasesCollection": {"items": [{"version": "v5.0.4", "hardwareUnitLinksCollection": {"items": list(summary_links)}}]}},
        {"__typename": "PageSectionReleaseNotes",
         "engineDesktopReleasesCollection": {"items": list(desktop_history)},
         "engineOsReleasesCollection": {"items": list(os_history)}},
    ]}}}}
    return f'<html><body><div id="__next"></div><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></body></html>'


SUMMARY = [
    _ej_link("PRIME 4 G2", "5.1.0", "Denon DJ", "Standalone DJ Controller"),
    _ej_link("SYSTEM ONE", "5.0.4", "Rane", "Standalone DJ Controller"),
    _ej_link("SC6000 PRIME", "5.0.4", "Denon DJ", "DJ Player"),
]

ENGINE_PAGE = _ej_page(
    os_history=[
        _ej_release("v5.1.0", "2026-09-01", [_ej_link("PRIME 4 G2", "5.1.0", usb=False)],
                    _ej_notes("NOTE: Engine DJ 5.1.0 is exclusive to Denon DJ PRIME 4 G2 users.", bullets=["Onboard Stems Rendering"])),
        # The G2 is listed under 5.0.4 with the 5.1.0 updater: it never ran 5.0.4.
        _ej_release("v5.0.4", "2026-07-28", [_ej_link("PRIME 4 G2", "5.1.0"), _ej_link("SYSTEM ONE", "5.0.4"), _ej_link("SC6000 PRIME", "5.0.4")]),
        _ej_release("v4.6.0", "2026-02-26", [_ej_link("SYSTEM ONE", "4.6.0")]),
        _ej_release("v4.3.4", "2025-11-18", [_ej_link("SC6000 PRIME", "4.3.4")]),
    ],
    desktop_history=[
        {"__typename": "DownloadsEngineDesktopRelease", "version": "v5.1.0", "releaseDate": "2026-09-01T00:00:00.000Z",
         "releaseNotes": _ej_notes("Improvements and Fixes", bullets=["Improved drag-and-drop performance."])},
        {"__typename": "DownloadsEngineDesktopRelease", "version": "v4.3.4", "releaseDate": "2025-11-18T00:00:00.000Z"},
    ],
    summary_links=SUMMARY,
)


def _versions(devices, name):
    return [(fw.version, fw.release_date.date().isoformat()) for fw in devices[name][1]]


def test_enginedj_gives_each_unit_only_the_releases_that_list_it():
    """5.1.0 is exclusive to the PRIME 4 G2; 4.6.0 went to the SYSTEM ONE alone."""
    from src.scrapers.plugins.enginedj import EngineDJScraper

    devices = EngineDJScraper()._parse_page(ENGINE_PAGE)

    assert _versions(devices, "Rane SYSTEM ONE") == [("5.0.4", "2026-07-28"), ("4.6.0", "2026-02-26")]
    assert _versions(devices, "Denon DJ SC6000 PRIME") == [("5.0.4", "2026-07-28"), ("4.3.4", "2025-11-18")]


def test_enginedj_does_not_credit_a_unit_listed_with_another_releases_updater():
    """The URL-encoded "%205.1.0" must read as 5.1.0, not 205.1.0."""
    from src.scrapers.plugins.enginedj import EngineDJScraper

    devices = EngineDJScraper()._parse_page(ENGINE_PAGE)

    assert _versions(devices, "Denon DJ PRIME 4 G2") == [("5.1.0", "2026-09-01")]


def test_enginedj_names_units_with_the_brand_the_summary_section_carries():
    from src.scrapers.plugins.enginedj import EngineDJScraper

    devices = EngineDJScraper()._parse_page(ENGINE_PAGE)

    assert {name: device.category for name, (device, _) in devices.items()} == {
        "Denon DJ PRIME 4 G2": "midi_controller", "Rane SYSTEM ONE": "midi_controller",
        "Denon DJ SC6000 PRIME": "other", "Engine DJ Desktop": "vst_plugin",
    }
    assert devices["Rane SYSTEM ONE"][0].product_url == "https://example.com/system-one"


def test_enginedj_reads_desktop_releases_and_flattens_their_notes():
    from src.scrapers.plugins.enginedj import EngineDJScraper

    devices = EngineDJScraper()._parse_page(ENGINE_PAGE)
    desktop = devices["Engine DJ Desktop"][1]

    assert [(fw.version, fw.release_date) for fw in desktop] == [("5.1.0", datetime(2026, 9, 1)), ("4.3.4", datetime(2025, 11, 18))]
    assert desktop[0].changelog == "Improvements and Fixes\n- Improved drag-and-drop performance."
    assert devices["Denon DJ PRIME 4 G2"][1][0].changelog.endswith("- Onboard Stems Rendering")


@pytest.mark.asyncio
async def test_enginedj_lists_every_device_from_one_fetch():
    from src.scrapers.plugins.enginedj import EngineDJScraper as E

    scraper = E()
    asked = _stub_fetch(scraper, {E.DOWNLOADS_URL: ENGINE_PAGE})

    devices = (await scraper.fetch_device_list()).devices
    result = await scraper.fetch_firmware_versions("Rane SYSTEM ONE", E.DOWNLOADS_URL)

    assert asked == [E.DOWNLOADS_URL]
    assert len(devices) == 4
    assert result.firmware_versions[0].version == "5.0.4"


@pytest.mark.asyncio
async def test_enginedj_fails_loudly_without_os_releases():
    from src.scrapers.plugins.enginedj import EngineDJScraper as E

    scraper = E()
    _stub_fetch(scraper, {E.DOWNLOADS_URL: "<html><body>Maintenance</body></html>"})

    assert (await scraper.fetch_device_list()).success is False
