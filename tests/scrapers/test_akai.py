import json

import pytest


def _akai_payload() -> dict:
    return {"data": {"allBuilderModels": {"l1": [
        {"data": {"name": "MPC Studio", "url": "/mpc-studio",
                  "categories": {"lvl1": ["Products > Controllers"]},
                  "downloads": [
                      {"type": "Firmware Update", "version": "",
                       "description": "MPC Studio Windows Firmware Update v1.10",
                       "url": "https://x/1"},
                      {"type": "Firmware Update", "version": "",
                       "description": "MPC 2.11.10 Software Update (74.64 kB)",
                       "url": "https://x/2"},
                      {"type": "User Manual", "version": "9",
                       "description": "MPC Studio User Guide", "url": "https://x/3"},
                      {"type": "Driver", "version": "2.30",
                       "description": "USB driver", "url": "https://x/4"},
                  ]}},
        {"data": {"name": "Advance 25", "url": "/advance-25",
                  "categories": {"lvl1": ["Products > Controllers"]},
                  "downloads": [
                      {"type": "Firmware Update", "version": "",
                       "description": "Advance 25 - Firmware ReadMe (76.74 kB)",
                       "url": "https://x/5"},
                      {"type": "Firmware Update", "version": "",
                       "description": "Advance 25 - Firmware Updater v1.0.10 (PC)",
                       "url": "https://x/6"},
                  ]}},
        {"data": {"name": "MPC2500", "url": "/mpc2500",
                  "categories": {"lvl1": ["Products > Instruments"]},
                  "downloads": [
                      {"type": "Firmware Update", "version": "",
                       "description": "MPC2500 Operating System [v1.24] (418.73 kB)",
                       "url": "https://x/7"},
                  ]}},
        {"data": {"name": "Legacy MPC Firmware (Gen 1)", "url": "/legacy",
                  "categories": {"lvl1": ["Products > Collections"]},
                  "downloads": [
                      {"type": "Firmware Update", "version": "3.9",
                       "description": "USB updater 3.9", "url": "https://x/8"},
                  ]}},
    ], "l2": []}}}


def test_akai_does_not_read_a_file_size_as_a_version():
    """"Firmware ReadMe (76.74 kB)" gave Advance 25 a firmware of 76.74."""
    from src.scrapers.plugins.akai import AkaiScraper

    catalogue = AkaiScraper()._parse_catalogue(_akai_payload())
    advance = [fw.version for fw in catalogue["Advance 25"]["versions"]]

    assert advance == ["1.0.10"]
    assert "76.74" not in advance


def test_akai_does_not_read_the_mpc_software_as_device_firmware():
    """"MPC 2.11.10 Software Update" sits in the firmware array and is not the
    device's firmware. Only a v-prefixed number in prose is trusted."""
    from src.scrapers.plugins.akai import AkaiScraper

    catalogue = AkaiScraper()._parse_catalogue(_akai_payload())
    studio = [fw.version for fw in catalogue["MPC Studio"]["versions"]]

    assert studio == ["1.10"]
    assert "2.11.10" not in studio


def test_akai_reads_a_bracketed_version_from_prose():
    from src.scrapers.plugins.akai import AkaiScraper

    catalogue = AkaiScraper()._parse_catalogue(_akai_payload())

    assert [fw.version for fw in catalogue["MPC2500"]["versions"]] == ["1.24"]


def test_akai_filters_on_type_not_on_wording():
    """256 user manuals, 76 editors and 53 drivers share the downloads array."""
    from src.scrapers.plugins.akai import AkaiScraper

    catalogue = AkaiScraper()._parse_catalogue(_akai_payload())
    studio = [fw.version for fw in catalogue["MPC Studio"]["versions"]]

    assert "9" not in studio, "took the user manual revision"
    assert "2.30" not in studio, "took the USB driver"


def test_akai_excludes_the_legacy_updater_archives():
    """Not products but archives of every historical MPC updater."""
    from src.scrapers.plugins.akai import AkaiScraper

    catalogue = AkaiScraper()._parse_catalogue(_akai_payload())

    assert "Legacy MPC Firmware (Gen 1)" not in catalogue
    assert set(catalogue) == {"MPC Studio", "Advance 25", "MPC2500"}


@pytest.mark.asyncio
async def test_akai_discovers_the_gatsby_query_hash():
    """The hash is a build artefact: hardcoding it means a rebuild kills the scraper.

    page-data.json for the downloads route names it under staticQueryHashes.
    """
    import json

    from src.scrapers.plugins.akai import AkaiScraper

    scraper = AkaiScraper()
    asked = []

    async def fake_fetch(url, **kwargs):
        asked.append(url)
        if url == AkaiScraper.PAGE_DATA:
            return json.dumps({"staticQueryHashes": ["111", "222"]})
        if url == AkaiScraper.STATIC_QUERY.format("111"):
            return json.dumps({"data": {}})          # the other query, no products
        if url == AkaiScraper.STATIC_QUERY.format("222"):
            return json.dumps(_akai_payload())
        return None

    scraper.fetch_page = fake_fetch
    devices = await scraper.fetch_device_list()

    assert devices.success is True
    assert AkaiScraper.STATIC_QUERY.format("222") in asked
    assert len(devices.devices) == 3
