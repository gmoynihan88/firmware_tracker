import json

import pytest


def _novation_manifest() -> str:
    import json

    return json.dumps({"firmwares": [
        {"id": 1, "product": "peak", "firmware_type": "firmware", "build": 400,
         "version": "2.1", "release_notes": "Adds new oscillator modes",
         "url": "https://components.novationmusic.com/api/v2/firmwares/1/file"},
        {"id": 2, "product": "peak", "firmware_type": "firmware", "build": 380,
         "version": "2.0", "release_notes": "",
         "url": "https://components.novationmusic.com/api/v2/firmwares/2/file"},
        # Same version string as the firmware above, different component entirely.
        {"id": 3, "product": "peak", "firmware_type": "fpga", "build": 469,
         "version": "2.1", "release_notes": "FPGA image",
         "url": "https://components.novationmusic.com/api/v2/firmwares/3/file"},
        {"id": 4, "product": "bsii", "firmware_type": "firmware", "build": 554,
         "version": "4.15", "release_notes": "Fixes tuning drift",
         "url": "https://components.novationmusic.com/api/v2/firmwares/4/file"},
        {"id": 5, "product": "brand-new-thing", "firmware_type": "firmware",
         "build": 1, "version": "1.0", "release_notes": "",
         "url": "https://components.novationmusic.com/api/v2/firmwares/5/file"},
    ]})


def _novation_scraper(payload=None):
    from src.scrapers.plugins.novation import NovationScraper

    scraper = NovationScraper()

    async def fake_fetch(url, **kwargs):
        return _novation_manifest() if payload is None else payload

    scraper.fetch_page = fake_fetch
    return scraper


@pytest.mark.asyncio
async def test_novation_excludes_fpga_which_shares_firmware_version_numbers():
    """Not tidiness: Peak has an fpga 2.1 and a firmware 2.1.

    Keeping both means one silently overwrites the other when versions are
    deduplicated, and the download stored for "Peak 2.1" becomes the FPGA image.
    """
    scraper = _novation_scraper()
    result = await scraper.fetch_firmware_versions("Peak", "")

    assert [fw.version for fw in result.firmware_versions] == ["2.1", "2.0"]
    fpga = [fw for fw in result.firmware_versions if "FPGA" in (fw.changelog or "")]
    assert fpga == [], "took the FPGA image as the instrument's firmware"
    assert result.firmware_versions[0].download_url.endswith("/1/file")


@pytest.mark.asyncio
async def test_novation_uses_the_vendors_spelling_not_the_slug():
    """Title-casing the manifest slugs gives "Bsii" and "Sl Mkiii"."""
    scraper = _novation_scraper()
    devices = await scraper.fetch_device_list()
    names = {d.name for d in devices.devices}

    assert "Bass Station II" in names
    assert "Bsii" not in names


@pytest.mark.asyncio
async def test_novation_still_reports_a_product_it_has_no_name_for():
    """A product added since PRODUCTS was written must not vanish.

    An awkward name in the catalogue is visible and someone fixes it; a silently
    dropped product is neither visible nor fixable.
    """
    scraper = _novation_scraper()
    devices = await scraper.fetch_device_list()
    names = {d.name for d in devices.devices}

    assert "Brand New Thing" in names


@pytest.mark.asyncio
async def test_novation_claims_no_release_dates():
    """The manifest has no date field at all, so every version here is undated.

    Asserted rather than assumed, because a date invented for 112 versions would be
    the most convincing wrong data in the project.
    """
    scraper = _novation_scraper()
    result = await scraper.fetch_firmware_versions("Bass Station II", "")

    assert result.firmware_versions
    assert all(fw.release_date is None for fw in result.firmware_versions)


@pytest.mark.asyncio
async def test_novation_fails_loudly_when_the_manifest_is_unreachable():
    """An empty device list would read as a vendor that publishes nothing —
    which is exactly what the downloads site already wrongly suggests."""
    scraper = _novation_scraper(payload=None)

    async def no_response(url, **kwargs):
        return None

    scraper.fetch_page = no_response
    result = await scraper.fetch_device_list()

    assert result.success is False
    assert "firmwares" in result.error


@pytest.mark.asyncio
async def test_novation_reads_the_manifest_once_per_run():
    """Every product's versions come from one response; asking again must not refetch."""
    from src.scrapers.plugins.novation import NovationScraper

    scraper = NovationScraper()
    calls = []

    async def counting_fetch(url, **kwargs):
        calls.append(url)
        return _novation_manifest()

    scraper.fetch_page = counting_fetch

    await scraper.fetch_device_list()
    await scraper.fetch_firmware_versions("Peak", "")
    await scraper.fetch_firmware_versions("Bass Station II", "")

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_novation_fails_rather_than_crashes_on_a_broken_manifest():
    """An endpoint that starts returning HTML is a breakage, not an empty vendor."""
    for payload in ("<html>maintenance</html>", '{"firmwares": []}'):
        scraper = _novation_scraper(payload=payload)
        result = await scraper.fetch_device_list()
        assert result.success is False, f"accepted {payload[:20]!r}"


@pytest.mark.asyncio
async def test_novation_reports_a_withdrawn_product_as_an_absence():
    """A device row outliving its manifest entry is not a failure to investigate.

    The endpoint answered; Novation simply stopped listing it. Reporting failure
    would raise a false alarm on every run for as long as the row exists.
    """
    scraper = _novation_scraper()
    result = await scraper.fetch_firmware_versions("Discontinued Thing", "")

    assert result.success is True
    assert result.firmware_versions == []
