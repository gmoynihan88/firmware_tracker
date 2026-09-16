import asyncio
import json

import pytest


@pytest.mark.asyncio
async def test_universal_audio_reports_no_version_rather_than_a_guess():
    """UA publishes no per-plugin versions, and claiming one is worse than admitting it.

    The table this replaced held the versions installed on the developer's own
    machine, so it reported every UA plugin as up to date by construction and could
    never report anything else. Reporting nothing puts them in
    devices_without_firmware, which the dashboard shows as "Firmware Unknown".
    """
    from src.scrapers.plugins.universal_audio import UniversalAudioScraper

    scraper = UniversalAudioScraper()

    # Success, not failure: the fetch did not break, the version simply is not public.
    result = await scraper.fetch_firmware_versions("Polymax", "https://example.invalid")
    assert result.success is True
    assert result.firmware_versions == []

    # No hardcoded version table survives anywhere on the class.
    assert not hasattr(scraper, "KNOWN_FIRMWARE")


@pytest.mark.asyncio
async def test_universal_audio_points_devices_at_the_release_notes():
    """Each kind of product links to the notes that actually cover it.

    The plugins have no firmware page, so Details opens the nearest useful thing.
    The pedals do have one, and pointing them at the plugins' notes would send
    someone to an article that never mentions their pedal.

    Stubbed rather than live: the pedal list now comes from the shop, and a test that
    reaches the network fails when the network does.
    """
    import json

    from src.scrapers.plugins.universal_audio import UniversalAudioScraper

    scraper = UniversalAudioScraper()

    async def fake_fetch(url, **kwargs):
        return json.dumps({"products": [
            {"title": "Golden Reverberator", "tags": ["category guitar:UAFX Pedals"]},
            {"title": "OX Amp Top Box", "tags": ["category guitar:Guitar Amp Load Box"]},
        ]})

    scraper.fetch_page = fake_fetch
    result = await scraper.fetch_device_list()
    by_name = {d.name: d for d in result.devices}

    assert len(result.devices) == 12  # 10 plugins + 2 discovered pedals

    plugins = [d for d in result.devices if d.category == "vst_plugin"]
    assert len(plugins) == 10
    for device in plugins:
        assert device.firmware_page_url == UniversalAudioScraper.RELEASE_NOTES_URL
        # The product page is still kept, just not as the firmware link.
        assert "uaudio.com/uad-plugins/" in device.product_url

    assert by_name["Golden Reverberator"].firmware_page_url == UniversalAudioScraper.UAFX_NOTES_URL
    assert by_name["OX Amp Top Box"].firmware_page_url == UniversalAudioScraper.OX_NOTES_URL


def _ua_uafx_article() -> str:
    """Version in an h2, date in the h4 under it, changes in the list after."""
    return """
    <h2>UAFX Version 2.0.2</h2>
    <h4>December 22, 2025</h4>
    <p><strong>Improved</strong></p>
    <ul><li>Fixed Bypass, PC, and CC interactions</li></ul>
    <h2>UAFX Version 1.1.14</h2>
    <h4>November 21, 2024</h4>
    <ul><li>(Knuckles, ANTI) Latency is reduced by 1.3 ms</li></ul>
    """


def _ua_ox_article() -> str:
    """Version and date in one heading, and an install guide shaped almost the same.

    "How To Install OX Firmware v1.2" is an instruction that names a version and
    carries no date. A version-only pattern records it as a release, and it would
    reappear every time UA edited the article.
    """
    return """
    <h2>How To Install OX Firmware v1.2</h2>
    <h3>Create your USB drive firmware updater</h3>
    <h1>OX Firmware Version History</h1>
    <h4>OX Firmware v1.2 &mdash; November 12, 2019</h4>
    <p>Adds support for new speaker cabinets.</p>
    <h4>OX Firmware v1.1 &mdash; August 8, 2018</h4>
    <p>Improved rig switching.</p>
    """


def test_ua_pairs_each_uafx_version_with_its_own_date():
    from src.scrapers.plugins.universal_audio import UniversalAudioScraper

    versions = UniversalAudioScraper()._parse_uafx(_ua_uafx_article())

    assert [(fw.version, fw.release_date.strftime("%Y-%m-%d")) for fw in versions] == [
        ("2.0.2", "2025-12-22"),
        ("1.1.14", "2024-11-21"),
    ]
    assert "Bypass" in versions[0].changelog


def test_ua_keeps_each_uafx_note_on_its_own_line():
    """As served: labelled groups, a <br> inside an item, words split across spans.

    The notes were one run-on line from the first list only: 2.0.0 lost three of its
    four groups, and "(t</span><span>o reduce" read "(t o reduce".
    """
    from src.scrapers.plugins.universal_audio import UniversalAudioScraper

    article = """
    <h2 id="h_1">UAFX Version 2.0.0</h2><h4 id="h_2">November 11, 2025</h4><p><strong>All UAFX pedals with two footswitches</strong></p><ul>
    <li data-list-item-id="a">Bluetooth redesigned for faster connections<br>(requires <a href="https://www.uaudio.com/pages/download-uafx-pedals"><strong>UAFX Control</strong></a> v3)</li>
    <li data-list-item-id="b">USB MIDI Control Change (open beta)</li>
    </ul><p><strong>All Amp pedals</strong></p><ul><li data-list-item-id="c">Access up to four presets from footswitches</li></ul>
    <h2 id="h_3">UAFX Version 1.1.14</h2><h4 id="h_4"><span style="font-weight: 400;">November 21, 2024</span></h4><ul>
    <li data-list-item-id="d">
    <span style="font-weight: 400;">(Knuckles) Reduced Master setting for clarity (t</span><span style="font-weight: 400;">o reduce it: Factory reset the pedal, or in </span><a href="https://www.uaudio.com/pages/download-uafx-pedals"><span style="font-weight: 400;"><strong>UAFX Control</strong></span></a><span style="font-weight: 400;">, Revert to Default)</span>
    </li>
    </ul>
    <h2 id="h_5">UAFX Version 1.1.3</h2><h4 id="h_6">April 11, 2023</h4><ul><li>New Split dual-mono mode* (Galaxy)</li></ul>
    <p>*Requires UAFX Control v2.2.0 or newer</p>
    <h2 id="h_7">UAFX Version 1.0.1</h2><p>June 22, 2021</p><ul><li>Support for UAFX Control mobile app</li></ul><p></p>
    """

    versions = {fw.version: fw for fw in UniversalAudioScraper()._parse_uafx(article)}

    assert versions["2.0.0"].changelog == (
        "All UAFX pedals with two footswitches\n"
        "- Bluetooth redesigned for faster connections (requires UAFX Control v3)\n"
        "- USB MIDI Control Change (open beta)\n"
        "All Amp pedals\n"
        "- Access up to four presets from footswitches"
    )
    assert versions["1.1.14"].changelog == (
        "- (Knuckles) Reduced Master setting for clarity (to reduce it: Factory reset the pedal, "
        "or in UAFX Control, Revert to Default)"
    )
    # The footnote belongs to the release it follows.
    assert versions["1.1.3"].changelog == "- New Split dual-mono mode* (Galaxy)\n*Requires UAFX Control v2.2.0 or newer"
    # A date in a paragraph is still the date, not a note.
    assert versions["1.0.1"].release_date.strftime("%Y-%m-%d") == "2021-06-22"
    assert versions["1.0.1"].changelog == "- Support for UAFX Control mobile app"


def test_ua_indents_the_ox_notes_nested_lists():
    from src.scrapers.plugins.universal_audio import UniversalAudioScraper

    article = """
    <h1>OX Firmware Version History</h1>
    <p><em>Note: For optimum results, use the same version of the OX Amp Top Box app and the firmware.</em></p>
    <h4>OX Firmware v1.2 — November 12, 2019</h4>
    <ul>
    <li>Five new speaker cabinet models
    <ul>
    <li>4x12 UK Vee 30</li>
    <li>2x12 JBF 120</li>
    </ul>
    </li>
    <li>27 new Rigs based on tones from legendary artists and albums</li>
    </ul>
    <h4>OX Firmware v1.1 — August 8, 2018</h4>
    <ul>
    <li>General stability improvements</li>
    </ul>
    """

    versions = UniversalAudioScraper()._parse_ox(article)

    assert versions[0].changelog == (
        "- Five new speaker cabinet models\n"
        "  - 4x12 UK Vee 30\n"
        "  - 2x12 JBF 120\n"
        "- 27 new Rigs based on tones from legendary artists and albums"
    )
    # Stops at the next release rather than running on into it.
    assert versions[1].changelog == "- General stability improvements"


def test_ua_skips_the_ox_install_guide_that_names_a_version():
    """The date in the heading is what separates a release from an instruction."""
    from src.scrapers.plugins.universal_audio import UniversalAudioScraper

    versions = UniversalAudioScraper()._parse_ox(_ua_ox_article())

    assert [(fw.version, fw.release_date.strftime("%Y-%m-%d")) for fw in versions] == [
        ("1.2", "2019-11-12"),
        ("1.1", "2018-08-08"),
    ]
    assert len(versions) == 2, "took the How To Install heading as a release"


def test_ua_separates_uafx_pedals_from_the_ox_in_one_collection():
    """Both sit in the guitar-pedals collection and read different release notes."""
    import asyncio
    import json

    from src.scrapers.plugins.universal_audio import UniversalAudioScraper

    products = {"products": [
        {"title": "Golden Reverberator", "tags": ["category guitar:UAFX Pedals"]},
        {"title": "OX Amp Top Box", "tags": ["category guitar:Guitar Amp Load Box"]},
        {"title": "Some Cable", "tags": ["category:Accessory"]},
    ]}

    scraper = UniversalAudioScraper()

    async def fake_fetch(url, **kwargs):
        if "products.json" in url:
            return json.dumps(products)
        body = _ua_uafx_article() if UniversalAudioScraper.UAFX_ARTICLE in url else _ua_ox_article()
        return json.dumps({"article": {"body": body}})

    scraper.fetch_page = fake_fetch

    devices = asyncio.run(scraper.fetch_device_list())
    names = [d.name for d in devices.devices]
    assert "Golden Reverberator" in names
    assert "OX Amp Top Box" in names
    assert "Some Cable" not in names, "an accessory is not a device"

    pedal = asyncio.run(scraper.fetch_firmware_versions("Golden Reverberator", ""))
    ox = asyncio.run(scraper.fetch_firmware_versions("OX Amp Top Box", ""))
    assert [fw.version for fw in pedal.firmware_versions] == ["2.0.2", "1.1.14"]
    assert [fw.version for fw in ox.firmware_versions] == ["1.2", "1.1"]


def test_ua_plugins_still_report_nothing():
    """The ten UADX plugins publish no version, and that has not changed.

    They must keep reporting success with an empty list rather than being swept into
    the pedals' release notes, which would give every plugin the pedal firmware.
    """
    import asyncio
    import json

    from src.scrapers.plugins.universal_audio import UniversalAudioScraper

    scraper = UniversalAudioScraper()

    async def fake_fetch(url, **kwargs):
        if "products.json" in url:
            return json.dumps({"products": [
                {"title": "Golden Reverberator", "tags": ["category guitar:UAFX Pedals"]},
            ]})
        return json.dumps({"article": {"body": _ua_uafx_article()}})

    scraper.fetch_page = fake_fetch
    result = asyncio.run(scraper.fetch_firmware_versions("Distressor", ""))

    assert result.success is True
    assert result.firmware_versions == []
