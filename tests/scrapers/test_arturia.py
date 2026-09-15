import asyncio
import json


def _arturia_catalogue():
    """Products and resources, trimmed to the cases that matter."""
    products = [
        {"product_id": 510, "display_name": "MiniFreak", "product_name": "MiniFreak",
         "product_type": "HardwareSynth", "category_alias": "hybrid-synths", "slug": "minifreak"},
        {"product_id": 77, "display_name": "KeyLab 88", "product_name": "KeyLab 88",
         "product_type": "MIDIKeyboard", "category_alias": "midi", "slug": "keylab-88"},
        # One interface, two catalogue entries, different generations.
        {"product_id": 349, "display_name": "AudioFuse", "product_name": "AudioFuse",
         "product_type": "AudioInterface", "category_alias": "audio", "slug": "audiofuse"},
        {"product_id": 107, "display_name": "AudioFuse", "product_name": "AudioFuse",
         "product_type": "AudioInterface", "category_alias": "audio", "slug": "audiofuse"},
        {"product_id": 225, "display_name": "Pigments", "product_name": "Pigments",
         "product_type": "SoftwareInstrument", "category_alias": "software-instruments",
         "slug": "pigments"},
        # Content, not a product with a firmware line.
        {"product_id": 900, "display_name": "Jersey Beats", "product_name": "Jersey Beats",
         "product_type": "PresetPack", "category_alias": "in-app", "slug": "jersey-beats"},
    ]
    resources = [
        {"type": "firmware", "product_id": 510, "version": "4.0.1",
         "release_date": "2025-06-23T12:00:00.000+00:00", "permalink": "https://dl/mf401.mff",
         "latest": True},
        {"type": "firmware", "product_id": 510, "version": "3.0.0",
         "release_date": "2024-12-12T12:00:00.000+00:00", "permalink": "https://dl/mf300.mff",
         "latest": False},
        # The editor, on the same product page and two releases ahead of the pedal.
        {"type": "soft", "product_id": 510, "version": "4.0.2.6369",
         "release_date": "2025-07-01T12:00:00.000+00:00", "permalink": "https://dl/mfv.pkg",
         "latest": True},
        {"type": "manual", "product_id": 510, "version": "4",
         "release_date": "2025-01-01T12:00:00.000+00:00", "permalink": "https://dl/mf.pdf",
         "latest": True},
        # latest=True on three records, and the newest is the one without a platform.
        {"type": "firmware", "product_id": 77, "version": "1.2.0.6", "platform_type": "",
         "release_date": "2016-04-25T12:00:00.000+00:00", "permalink": "https://dl/k1206",
         "latest": True},
        {"type": "firmware", "product_id": 77, "version": "1.1.0.4", "platform_type": "mac",
         "release_date": "2015-08-06T12:00:00.000+00:00", "permalink": "https://dl/k1104m",
         "latest": True},
        {"type": "firmware", "product_id": 77, "version": "1.1.0.4", "platform_type": "windows",
         "release_date": "2015-08-06T12:00:00.000+00:00", "permalink": "https://dl/k1104w",
         "latest": True},
        # Current entry carries only the latest; the old entry carries the history.
        {"type": "firmware", "product_id": 349, "version": "1.2.3",
         "release_date": "2020-03-10T12:00:00.000+00:00", "permalink": "https://dl/af123",
         "latest": True},
        {"type": "firmware", "product_id": 107, "version": "1.1.0",
         "release_date": "2017-11-27T12:00:00.000+00:00", "permalink": "https://dl/af110",
         "latest": False},
        {"type": "firmware", "product_id": 107, "version": "1.0.4",
         "release_date": "2017-05-31T12:00:00.000+00:00", "permalink": "https://dl/af104",
         "latest": False},
        # One release, two platform builds, dated a day apart.
        {"type": "soft", "product_id": 225, "version": "7.0.1", "platform_type": "windows",
         "release_date": "2026-07-30T12:00:00.000+00:00", "permalink": "https://dl/pig-win",
         "latest": True},
        {"type": "soft", "product_id": 225, "version": "7.0.1", "platform_type": "mac",
         "release_date": "2026-07-29T12:00:00.000+00:00", "permalink": "https://dl/pig-mac",
         "latest": True},
        {"type": "soft", "product_id": 900, "version": "1.0.0",
         "release_date": "2026-01-01T12:00:00.000+00:00", "permalink": "https://dl/jb",
         "latest": True},
    ]
    return products, resources


def _arturia_loaded():
    """A scraper with the fixture catalogue already in place."""
    import json

    from src.scrapers.plugins.arturia import ArturiaScraper

    products, resources = _arturia_catalogue()
    scraper = ArturiaScraper()

    async def fake_fetch(url, **kwargs):
        return json.dumps(products if url == scraper.PRODUCTS_API else resources)

    scraper.fetch_page = fake_fetch
    return scraper


def test_arturia_takes_the_firmware_not_the_editor_or_the_manual():
    """One product_id carries all three, distinguished only by `type`.

    MiniFreak V is 4.0.2.6369 while the instrument is on 4.0.1, which is the
    companion-app trap in its usual form: a real version, on the right page, for the
    wrong thing. The manual is "version 4", the User Guide V4 false positive.
    """
    import asyncio

    scraper = _arturia_loaded()
    result = asyncio.run(scraper.fetch_firmware_versions("MiniFreak", ""))
    found = {fw.version for fw in result.firmware_versions}

    assert found == {"4.0.1", "3.0.0"}
    assert "4.0.2.6369" not in found, "took the MiniFreak V editor"
    assert "4" not in found, "took the manual revision"


def test_arturia_ignores_the_per_platform_latest_flag():
    """KeyLab 88 flags three records latest, and two of them are two releases old."""
    import asyncio

    scraper = _arturia_loaded()
    result = asyncio.run(scraper.fetch_firmware_versions("KeyLab 88", ""))

    # Newest first, so the service's own max() and this agree.
    assert [fw.version for fw in result.firmware_versions] == ["1.2.0.6", "1.1.0.4"]


def test_arturia_merges_two_entries_for_one_product():
    """Both AudioFuse generations are the same interface, split across product ids.

    Keyed separately, the current entry would be a device with one version and no
    history, and the old one a second device holding the history nobody looks at.
    """
    import asyncio

    scraper = _arturia_loaded()
    devices = asyncio.run(scraper.fetch_device_list())
    names = [d.name for d in devices.devices]

    assert names.count("AudioFuse") == 1
    result = asyncio.run(scraper.fetch_firmware_versions("AudioFuse", ""))
    assert [fw.version for fw in result.firmware_versions] == ["1.2.3", "1.1.0", "1.0.4"]


def test_arturia_keeps_the_earlier_date_for_a_split_release():
    """Mac and Windows builds of one version are dated a day apart, 51 times."""
    import asyncio

    scraper = _arturia_loaded()
    result = asyncio.run(scraper.fetch_firmware_versions("Pigments", ""))

    assert len(result.firmware_versions) == 1
    assert result.firmware_versions[0].release_date.strftime("%Y-%m-%d") == "2026-07-29"


def test_arturia_excludes_content_from_the_device_list():
    """410 of Arturia's products are preset packs, which have no firmware line."""
    import asyncio

    scraper = _arturia_loaded()
    devices = asyncio.run(scraper.fetch_device_list())
    names = {d.name for d in devices.devices}

    assert "Jersey Beats" not in names
    assert names == {"MiniFreak", "KeyLab 88", "AudioFuse", "Pigments"}


def test_arturia_fails_loudly_when_an_endpoint_is_unreachable():
    """Both endpoints are required; an empty device list would read as a dead vendor."""
    import asyncio

    from src.scrapers.plugins.arturia import ArturiaScraper

    scraper = ArturiaScraper()

    async def no_response(url, **kwargs):
        return None

    scraper.fetch_page = no_response
    result = asyncio.run(scraper.fetch_device_list())

    assert result.success is False
    assert "API" in (result.error or "")
