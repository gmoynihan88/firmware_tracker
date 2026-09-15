import pytest

SITE = "https://www.soundcraft.com"


def _row(name, version, products, href=None, klass="download_firmware"):
    link = f'<a class="{klass}" href="{href}" label_method="name">{name}</a>' if href else name
    related = " , ".join(f'<a href="/en-US/products/{p.lower().replace(" ", "-")}">{p}</a>' for p in products)
    return f"<tr><td>{link}</td><td>{version}</td><td>{related} </td></tr>"


# As served: one table, a "Latest Version" column, and the products each row is for.
FIRMWARE = (
    "<table><thead><tr><td>Firmware</td><td>Latest Version</td><td>Related Products</td></tr></thead><tbody>"
    + _row("Notepad Firmware and Control Panel Setup - Apple", "2.0.4", ["Notepad-5", "Notepad-8FX"], f"{SITE}/en-US/softwares/notepad-firmware-apple")
    + _row("Notepad Firmware and Control Panel Setup - Windows", "2.0.4", ["Notepad-5", "Notepad-8FX"], f"{SITE}/en-US/softwares/notepad-firmware-windows")
    + _row("Ui12 Firmware Update", "1.0.7548", ["Ui12"], f"{SITE}/en-US/softwares/ui12-firmware-update-v1-0-7548")
    + _row("Ui24R Firmware Update", "3.3", ["Ui24R"], f"{SITE}/en-US/softwares/ui24r-firmware-update-v3-3")
    + _row("Ui24R Firmware Update", "3.5", ["Ui24R"], "https://adn.harmanpro.com/softwares/wares/2299/uiupdate-k-3.5.8328-ui24v3.zip")
    + _row("Ui24R Firmware Update", "3.0", [], f"{SITE}/en-US/softwares/ui24r-firmware-update-v3-0")
    + "</tbody></table>"
)

# Four columns here: Software, Latest Version, Platform, Related Products.
SOFTWARE = (
    "<table><thead><tr><td>Software</td><td>Latest Version</td><td>Platform</td><td>Related Products</td></tr></thead><tbody>"
    + '<tr><td><a class="software-direct-link" href="https://adn.harmanpro.com/ConnectedPASetup.exe">Connected PA App (Windows 7/10)</a></td><td></td><td>Windows 7/10</td><td><a href="/en-US/products/ui24r">Ui24R</a> </td></tr>'
    + '<tr><td><a href="https://adn.harmanpro.com/Multi-channelUSBAudio.exe">Multi-Channel USB Audio Driver Setup v3.20.0 (Windows)</a></td><td>3.20.0</td><td>Windows</td><td><a href="/en-US/products/ui24r">Ui24R</a> </td></tr>'
    + '<tr><td><a href="/en-US/softwares/si-impact-console-software-v2-2-build-1">Si Impact Console Software v2.2 build 1</a></td><td>2.2 build 1</td><td></td><td><a href="/en-US/products/si-impact">Si Impact</a> </td></tr>'
    + '<tr><td><a href="/en-US/softwares/si-offline-impact-v2-2-build-1">Si Offline Impact v2.2 build 1</a></td><td>2.2 build 1</td><td></td><td><a href="/en-US/products/si-impact">Si Impact</a> </td></tr>'
    + '<tr><td><a href="/en-US/softwares/si-expression-console-updater-v2-2-build-1">Si Expression Console Updater v2.2 build 1</a></td><td>2.2 build 1</td><td></td><td><a href="/en-US/products/si-expression-1">Si Expression 1</a> , <a href="/en-US/products/si-expression-2">Si Expression 2</a> </td></tr>'
    + '<tr><td><a href="/en-US/softwares/soundcraft-virtual-vi-v6-4-8-360">Soundcraft Virtual Vi v6.4.8.360</a></td><td>6.4.8.360</td><td></td><td><a href="/en-US/products/vi3000">Vi3000</a> </td></tr>'
    + '<tr><td><a href="/en-US/softwares/update_console-7z-v6-4-8-360">Update_Console.7z v6.4.8.360</a></td><td>6.4.8.360</td><td></td><td><a href="/en-US/products/vi400-600-upgrade">Vi400/600 Upgrade</a> , <a href="/en-US/products/vi3000">Vi3000</a> </td></tr>'
    + '<tr><td><a href="/en-US/softwares/previous-vi3000-software-update-v5-0-1-253">[PREVIOUS] Vi3000 Software Update v5.0.1.253</a></td><td>5.0.1.253</td><td></td><td><a href="/en-US/products/vi3000">Vi3000</a> </td></tr>'
    + '<tr><td><a href="/en-US/softwares/previous-vi3000-offline-editor-v5-0-0-235">[PREVIOUS] Vi3000 Offline Editor v5.0.0.235</a></td><td>5.0.0.235</td><td></td><td><a href="/en-US/products/vi3000">Vi3000</a> </td></tr>'
    + '<tr><td><a href="/en-US/softwares/vi3000-downgrader">Vi3000 Downgrader from V6.x to V5.x</a></td><td></td><td></td><td><a href="/en-US/products/vi3000">Vi3000</a> </td></tr>'
    + "</tbody></table>"
)

PAGES = {
    "https://www.soundcraft.com/en-US/firmware": FIRMWARE,
    "https://www.soundcraft.com/en-US/software": SOFTWARE,
}


def _scraper(pages=PAGES):
    from src.scrapers.plugins.soundcraft import SoundcraftScraper

    scraper = SoundcraftScraper()
    fetched = []

    async def _page(url, *_args, **_kwargs):
        fetched.append(url)
        return pages.get(url)

    scraper.fetch_page = _page
    return scraper, fetched


async def _versions(scraper, device):
    result = await scraper.fetch_firmware_versions(device, "")
    assert result.success, result.error
    return [fw.version for fw in result.firmware_versions]


@pytest.mark.asyncio
async def test_soundcraft_lists_console_firmware_not_editors_drivers_or_apps():
    scraper, _ = _scraper()

    listing = await scraper.fetch_device_list()

    assert listing.success is True
    assert sorted(d.name for d in listing.devices) == [
        "Notepad-5", "Notepad-8FX", "Si Expression 1", "Si Expression 2", "Si Impact", "Ui12", "Ui24R", "Vi3000",
    ]
    # Si Offline Impact, the USB driver, Connected PA, Virtual Vi, the Vi3000 Offline
    # Editor and the downgrader are all on these pages and none is console firmware.
    assert await _versions(scraper, "Si Impact") == ["2.2 build 1"]
    assert await _versions(scraper, "Vi3000") == ["6.4.8.360", "5.0.1.253"]


@pytest.mark.asyncio
async def test_soundcraft_keeps_every_row_of_a_product_and_collapses_repeats():
    """The Ui24R has three firmware rows; Notepad's two platform rows are one version.

    The 3.0 row lists no related product, so it is filed under the console its own
    name states. Without that its release is lost.
    """
    scraper, _ = _scraper()

    assert await _versions(scraper, "Ui24R") == ["3.5", "3.3", "3.0"]
    assert await _versions(scraper, "Notepad-5") == ["2.0.4"]


@pytest.mark.asyncio
async def test_soundcraft_leaves_out_an_upgrade_kit():
    """"Vi400/600 Upgrade" is a kit, not a console."""
    scraper, _ = _scraper()

    names = [d.name for d in (await scraper.fetch_device_list()).devices]

    assert "Vi400/600 Upgrade" not in names


@pytest.mark.asyncio
async def test_soundcraft_reports_no_dates():
    scraper, _ = _scraper()

    result = await scraper.fetch_firmware_versions("Ui24R", "")

    assert all(fw.release_date is None for fw in result.firmware_versions)
    assert result.firmware_versions[0].download_url.endswith("uiupdate-k-3.5.8328-ui24v3.zip")


@pytest.mark.asyncio
async def test_soundcraft_reads_each_page_once():
    scraper, fetched = _scraper()

    listing = await scraper.fetch_device_list()
    for device in listing.devices:
        await scraper.fetch_firmware_versions(device.name, device.firmware_page_url)

    assert sorted(fetched) == sorted(PAGES)


@pytest.mark.asyncio
async def test_soundcraft_waits_the_crawl_delay_robots_asks_for():
    """robots.txt: "User-agent: ClaudeBot / Crawl-delay: 10"."""
    import asyncio

    from src.scrapers.plugins.soundcraft import SoundcraftScraper

    scraper = SoundcraftScraper()
    assert scraper.CRAWL_DELAY == 10.0
    slept = []
    real_sleep = asyncio.sleep

    async def _sleep(seconds):
        slept.append(seconds)
        await real_sleep(0)

    asyncio.sleep = _sleep
    try:
        await scraper._rate_limit()  # the first request waits for nothing
        await scraper._rate_limit()
    finally:
        asyncio.sleep = real_sleep

    assert slept and 9 < slept[0] <= 10


@pytest.mark.asyncio
async def test_soundcraft_fails_loudly():
    assert (await _scraper({})[0].fetch_device_list()).success is False

    firmware_only = {"https://www.soundcraft.com/en-US/firmware": FIRMWARE}
    assert (await _scraper(firmware_only)[0].fetch_device_list()).success is False

    empty = dict(PAGES)
    empty["https://www.soundcraft.com/en-US/firmware"] = "<p>Maintenance</p>"
    empty["https://www.soundcraft.com/en-US/software"] = "<p>Maintenance</p>"
    assert (await _scraper(empty)[0].fetch_device_list()).success is False

    scraper, _ = _scraper()
    assert (await scraper.fetch_firmware_versions("Si Performer 3", "")).success is False
