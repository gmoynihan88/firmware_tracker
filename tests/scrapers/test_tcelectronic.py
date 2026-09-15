import pytest


def _rsc_page(downloads_json: str) -> str:
    """Build a page that mimics Next.js RSC streaming, splitting mid-value.

    The payload is deliberately cut across two pushes so the test fails if the
    parser goes back to scanning the raw document.
    """
    import json as _json

    payload = '{"product":{"downloads":' + downloads_json + '}}'
    half = len(payload) // 2
    parts = [payload[:half], payload[half:]]
    pushes = "".join(
        f'<script>self.__next_f.push([1,{_json.dumps(part)}])</script>' for part in parts
    )
    return f"<html><body>{pushes}</body></html>"


def test_tcelectronic_parses_firmware_from_rsc_payload():
    """Firmware entries with a version are kept; drivers, manuals and notes are not."""
    from src.scrapers.plugins.tcelectronic import TCElectronicScraper

    scraper = TCElectronicScraper()
    downloads = """[
        {"title": "Firmware Release Notes", "downloadType": "Firmware", "version": null,
         "fileUrl": "https://example.invalid/notes"},
        {"title": "Ditto Plus Firmware Mac", "downloadType": "Firmware", "version": "1.0.14",
         "fileUrl": "https://example.invalid/DittoPlus-1.0.14.dmg"},
        {"title": "Quick Start Guide", "downloadType": "Manual", "version": null,
         "fileUrl": "https://example.invalid/qsg.pdf"},
        {"title": "Ditto Plus Firmware PC", "downloadType": "Driver", "version": null,
         "fileUrl": "https://example.invalid/pc"},
        {"title": "Labelled", "downloadType": "Firmware", "version": "Version 1.3.11",
         "fileUrl": "https://example.invalid/x3"}
    ]"""

    parsed = scraper._extract_rsc_downloads(_rsc_page(downloads))
    assert parsed is not None and len(parsed) == 5

    firmware = scraper._firmware_from_downloads(parsed)
    # Release notes have no version, so they drop out; the label is stripped.
    assert [f.version for f in firmware] == ["1.0.14", "1.3.11"]
    assert firmware[0].download_url.endswith("DittoPlus-1.0.14.dmg")


def test_tcelectronic_no_downloads_array_is_a_failure():
    """A page without the payload is a scrape failure, not an absence of firmware."""
    from src.scrapers.plugins.tcelectronic import TCElectronicScraper

    scraper = TCElectronicScraper()
    assert scraper._extract_rsc_downloads("<html><body>Loading</body></html>") is None
    assert scraper._extract_rsc_downloads("") is None


def test_tcelectronic_empty_downloads_is_not_a_failure():
    """A rendered page listing no firmware is a valid, empty result.

    Hall of Fame 2 is the real case: TonePrint app and manuals, no firmware.
    """
    from src.scrapers.plugins.tcelectronic import TCElectronicScraper

    scraper = TCElectronicScraper()
    downloads = """[
        {"title": "TonePrint App", "downloadType": "Software", "version": "4.7.2",
         "fileUrl": "https://example.invalid/toneprint"},
        {"title": "Quick Start Guide", "downloadType": "Manual", "version": null,
         "fileUrl": "https://example.invalid/qsg.pdf"}
    ]"""

    parsed = scraper._extract_rsc_downloads(_rsc_page(downloads))
    assert parsed == parsed and len(parsed) == 2
    # Software and manuals are not firmware, so nothing is reported for the device.
    assert scraper._firmware_from_downloads(parsed) == []


def _pushed(payload: str) -> str:
    """Stream a payload across two RSC pushes, cut mid-value as Next.js does."""
    import json as _json

    half = len(payload) // 2
    return "<html><body>" + "".join(
        f"<script>self.__next_f.push([1,{_json.dumps(part)}])</script>"
        for part in (payload[:half], payload[half:])
    ) + "</body></html>"


def _catalogue_page(products):
    import json as _json

    items = [
        {"id": handle, "variantId": "$undefined", "name": name, "tagline": "", "category": "",
         "images": [], "price": 0, "rating": 0, "journeyTags": [], "trending": False}
        for handle, name in products
    ]
    return _pushed('1c:["$","$L2f",null,{"name":"ProductDiscovery","children":["$","$L30",null,'
                   '{"products":' + _json.dumps(items) + ',"totalCount":' + str(len(items)) + "}]}]")


def _downloads(*entries):
    import json as _json

    return _rsc_page(_json.dumps([
        {"title": title, "downloadType": kind, "version": version, "fileUrl": f"https://example.invalid/{i}"}
        for i, (title, kind, version) in enumerate(entries)
    ]))


TC_PAGES = {
    "https://www.tcelectronic.com/en/products?page=1": _catalogue_page([
        ("0709-aiu", "DITTO+ LOOPER"), ("0709-ahh", "HYPERGRAVITY COMPRESSOR"), ("0709-afs", "HALL OF FAME 2 REVERB"),
    ]),
    "https://www.tcelectronic.com/en/products?page=2": _catalogue_page([
        ("0815-aak", "TC2290-DT"), ("0842-aad", "CLARITY M STEREO"), ("0709-ajq", "COMBO DELUXE 65' PREAMP"),
    ]),
    "https://www.tcelectronic.com/en/products?page=3": _catalogue_page([]),
    "https://www.tcelectronic.com/en/products/0709-aiu": _downloads(
        ("Firmware Release Notes", "Firmware", None), ("Ditto Plus Firmware Mac", "Firmware", "1.0.14")),
    "https://www.tcelectronic.com/en/products/0709-ahh": _downloads(
        ("Hyper Gravity Firmware", "Firmware", "1.0.05"), ("TonePrint App", "Software", "4.7.2")),
    "https://www.tcelectronic.com/en/products/0709-afs": _downloads(
        ("TonePrint App", "Software", "4.7.2"), ("Manual", "Manual", None)),
    "https://www.tcelectronic.com/en/products/0815-aak": _downloads(("Firmware", "Firmware", "2.1.0")),
    "https://www.tcelectronic.com/en/products/0842-aad": _downloads(
        ("Firmware Release Note", "Firmware", "2"), ("Firmware", "Firmware", "2.0.3"), ("Firmware", "Firmware", "2.1.3")),
    "https://www.tcelectronic.com/en/products/0709-ajq": _downloads(("Firmware", "Firmware", "1.0.8")),
}


def _tc_scraper(pages=TC_PAGES):
    from src.scrapers.plugins.tcelectronic import TCElectronicScraper

    scraper = TCElectronicScraper()
    fetched = []

    async def _page(url, *_args, **_kwargs):
        fetched.append(url)
        return pages.get(url)

    scraper.fetch_page = _page
    return scraper, fetched


@pytest.mark.asyncio
async def test_tcelectronic_lists_every_catalogue_product_with_firmware():
    """Hall of Fame 2 publishes only the TonePrint app, so it is not listed."""
    scraper, _ = _tc_scraper()

    result = await scraper.fetch_device_list()

    assert result.success is True
    devices = {d.name: d for d in result.devices}
    assert set(devices) == {"Ditto+", "Hypergravity Compressor", "TC2290-DT", "Clarity M Stereo", "Combo Deluxe 65' Preamp"}
    assert devices["Ditto+"].firmware_page_url == "https://www.tcelectronic.com/en/products/0709-aiu"


@pytest.mark.asyncio
async def test_tcelectronic_names_new_products_without_shouting():
    """Catalogued rows keep their names by handle; new ones are title-cased word by word."""
    scraper, _ = _tc_scraper()

    names = {d.name for d in (await scraper.fetch_device_list()).devices}

    assert "Ditto+" in names and "DITTO+ LOOPER" not in names
    # Words with digits or symbols are left as the vendor writes them.
    assert "TC2290-DT" in names and "Combo Deluxe 65' Preamp" in names


@pytest.mark.asyncio
async def test_tcelectronic_files_products_by_their_line():
    scraper, _ = _tc_scraper()

    categories = {d.name: d.category for d in (await scraper.fetch_device_list()).devices}

    assert categories["Hypergravity Compressor"] == "guitar_pedal"
    assert categories["TC2290-DT"] == "midi_controller"
    assert categories["Clarity M Stereo"] == "other"


@pytest.mark.asyncio
async def test_tcelectronic_ignores_a_release_note_numbered_without_a_dot():
    """Clarity M Stereo's "Firmware Release Note" is typed Firmware with version "2"."""
    scraper, _ = _tc_scraper()

    result = await scraper.fetch_firmware_versions("Clarity M Stereo", "")

    assert [fw.version for fw in result.firmware_versions] == ["2.0.3", "2.1.3"]


@pytest.mark.asyncio
async def test_tcelectronic_reads_each_page_once_per_scrape():
    scraper, fetched = _tc_scraper()

    listing = await scraper.fetch_device_list()
    for device in listing.devices:
        await scraper.fetch_firmware_versions(device.name, device.firmware_page_url)

    assert sorted(fetched) == sorted(TC_PAGES)


@pytest.mark.asyncio
async def test_tcelectronic_fails_rather_than_dropping_a_product():
    no_payload = dict(TC_PAGES, **{"https://www.tcelectronic.com/en/products/0815-aak": "<html><body>Loading</body></html>"})
    assert (await _tc_scraper(no_payload)[0].fetch_device_list()).success is False

    no_catalogue = dict(TC_PAGES, **{"https://www.tcelectronic.com/en/products?page=2": "<html><body>Maintenance</body></html>"})
    assert (await _tc_scraper(no_catalogue)[0].fetch_device_list()).success is False

    empty = {"https://www.tcelectronic.com/en/products?page=1": _catalogue_page([])}
    assert (await _tc_scraper(empty)[0].fetch_device_list()).success is False


@pytest.mark.asyncio
async def test_tcelectronic_reports_no_firmware_for_a_catalogued_row_without_any():
    """Ditto X4 and the rest of the old list's firmware-less pedals keep their rows."""
    scraper, _ = _tc_scraper()

    result = await scraper.fetch_firmware_versions("Hall of Fame 2", "https://www.tcelectronic.com/en/products/0709-afs")

    assert result.success is True
    assert result.firmware_versions == []
