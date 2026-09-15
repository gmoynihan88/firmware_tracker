import asyncio
from datetime import datetime

import pytest

from tests.support import _seed_unversioned, test_session_maker


@pytest.mark.asyncio
async def test_scrape_summary_reports_devices_without_firmware():
    """A device whose firmware fetch yields nothing must be named in the summary.

    Scrapers routinely return success=True with an empty version list, so without
    this the caller cannot tell a clean scrape from one that found nothing.
    """
    from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult
    from src.scrapers.registry import ScraperRegistry
    from src.scrapers import service as scraper_service

    class _StubScraper(BaseScraper):
        manufacturer_name = "Stub Audio"
        manufacturer_slug = "stubaudio"
        manufacturer_website = "https://stub.example.com"

        async def fetch_device_list(self) -> ScraperResult:
            return ScraperResult(
                success=True,
                devices=[
                    ScrapedDevice("Has Firmware", "guitar_pedal", "https://stub.example.com/a"),
                    ScrapedDevice("Empty Success", "guitar_pedal", "https://stub.example.com/b"),
                    ScrapedDevice("Hard Failure", "guitar_pedal", "https://stub.example.com/c"),
                ],
            )

        async def fetch_firmware_versions(self, device_name, firmware_page_url) -> ScraperResult:
            if device_name == "Has Firmware":
                return ScraperResult(success=True, firmware_versions=[ScrapedFirmware("1.0")])
            if device_name == "Empty Success":
                # The silent-failure shape: reports success, returns nothing.
                return ScraperResult(success=True, firmware_versions=[])
            return ScraperResult(success=False, error="page returned no firmware content")

    ScraperRegistry.register(_StubScraper)
    try:
        async with test_session_maker() as db:
            result = await scraper_service.scrape_manufacturer(db, "stubaudio")

        assert result["success"] is True
        # The two causes are reported separately: a product that genuinely has no
        # firmware is not the same as a fetch that broke.
        assert result["devices_without_firmware"] == ["Empty Success"]
        assert result["devices_failed"] == ["Hard Failure"]
    finally:
        ScraperRegistry._scrapers.pop("stubaudio", None)



@pytest.mark.asyncio
async def test_scrape_summary_reports_fetches_that_failed_even_when_every_device_succeeds():
    """A product whose page never loaded is simply absent, and the run reads as clean.

    Korg's Pa4X page takes 31s against a 30s limit. Korg leaves a product it could not
    load out of the catalogue, so every sweep reported "ok" with the Pa4X missing.
    """
    from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult
    from src.scrapers.registry import ScraperRegistry
    from src.scrapers import service as scraper_service

    class _DroppingScraper(BaseScraper):
        manufacturer_name = "Dropping Audio"
        manufacturer_slug = "droppingaudio"
        manufacturer_website = "https://dropping.example.com"

        async def fetch_device_list(self) -> ScraperResult:
            # What a scraper does after fetch_page returned None for one product page.
            self._record_fetch_failure("https://dropping.example.com/slow", "TimeoutError")
            return ScraperResult(success=True, devices=[
                ScrapedDevice("Loaded", "synthesizer", "https://dropping.example.com/loaded"),
            ])

        async def fetch_firmware_versions(self, device_name, firmware_page_url) -> ScraperResult:
            return ScraperResult(success=True, firmware_versions=[ScrapedFirmware("1.0")])

    ScraperRegistry.register(_DroppingScraper)
    try:
        async with test_session_maker() as db:
            result = await scraper_service.scrape_manufacturer(db, "droppingaudio")

        assert result["success"] is True
        assert result["devices_failed"] == []
        assert result["fetches_failed"] == ["https://dropping.example.com/slow: TimeoutError"]
    finally:
        ScraperRegistry._scrapers.pop("droppingaudio", None)

def test_scrape_budget_scales_with_device_count():
    """A fixed budget measures nothing; a 40-device scraper needs more than a 3-device one.

    At the old fixed 120s, Boss (16 devices at ~7s each) sat at 93% of budget while
    Native Instruments (40 devices) used 13%.
    """
    from src.scrapers.service import scrape_budget_for

    assert scrape_budget_for(3) < scrape_budget_for(16) < scrape_budget_for(40)
    # Comfortably above the observed worst case of ~7s per device.
    assert scrape_budget_for(16) >= 16 * 10
    # Degenerate counts do not produce a negative budget.
    assert scrape_budget_for(0) > 0
    assert scrape_budget_for(-5) > 0


@pytest.mark.asyncio
async def test_scrape_reports_partial_results_when_budget_runs_out(monkeypatch):
    """Running out of budget must return what was done, not discard the whole run.

    The old outer wait_for cancelled the scrape and replaced the summary with a bare
    failure, even though each device's data had already been committed -- so the
    database was right while the report claimed total failure.
    """
    from src.scrapers.base import BaseScraper, ScrapedDevice, ScrapedFirmware, ScraperResult
    from src.scrapers.registry import ScraperRegistry
    from src.scrapers import service as scraper_service

    class _SlowScraper(BaseScraper):
        manufacturer_name = "Slow Audio"
        manufacturer_slug = "slowaudio"
        manufacturer_website = "https://slow.example.com"

        async def fetch_device_list(self) -> ScraperResult:
            return ScraperResult(
                success=True,
                devices=[
                    ScrapedDevice(f"Slow {i}", "guitar_pedal", f"https://slow.example.com/{i}")
                    for i in range(5)
                ],
            )

        async def fetch_firmware_versions(self, device_name, firmware_page_url) -> ScraperResult:
            await asyncio.sleep(0.05)
            return ScraperResult(success=True, firmware_versions=[ScrapedFirmware("1.0")])

    # A budget that expires after roughly the first couple of devices.
    monkeypatch.setattr(scraper_service, "scrape_budget_for", lambda n: 0.06)

    ScraperRegistry.register(_SlowScraper)
    try:
        async with test_session_maker() as db:
            result = await scraper_service.scrape_manufacturer(db, "slowaudio")

        # The run reports success with partial results rather than failing outright.
        assert result["success"] is True
        assert result["devices_not_checked"], "expected some devices to be skipped"
        # And it did not silently skip everything.
        checked = 5 - len(result["devices_not_checked"])
        assert checked >= 1
    finally:
        ScraperRegistry._scrapers.pop("slowaudio", None)


def test_malformed_download_urls_are_rejected():
    """An earlier TAL scraper stored links with a failed relative join.

    `https://tal-software.com../../downloads/...` has dot-segments in the hostname,
    which no amount of normalising fixes -- it is a bad join, not a relative path.
    """
    from src.scrapers.service import _clean_url

    assert _clean_url("https://tal-software.com../../downloads/x.zip") is None
    assert _clean_url("/relative/path") is None
    assert _clean_url("ftp://example.com/x") is None
    assert _clean_url("") is None
    assert _clean_url(None) is None
    assert _clean_url("https://example.com/a.zip") == "https://example.com/a.zip"


def test_download_urls_can_only_be_web_links():
    """A stored download URL becomes an href on the device page and an ntfy link.

    Jinja escapes HTML, but escaping does nothing for a `javascript:` URL placed in
    an href -- the link is valid markup and runs on click. So the scheme check is
    the only thing between a hostile vendor page and script in the UI, and every
    way of writing a non-web scheme has to fail it.
    """
    from src.scrapers.service import _clean_url

    refused = [
        "javascript:alert(document.cookie)",
        "JavaScript:alert(1)",                       # scheme case varies
        "javascript://example.com/%0Aalert(1)",      # looks like it has a host
        " javascript:alert(1)",                      # leading whitespace
        "vbscript:msgbox(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "//evil.example/firmware.zip",               # scheme-relative
        "https:evil.example/firmware.zip",           # a scheme but no host
    ]
    for url in refused:
        assert _clean_url(url) is None, url

    # The positive control: real vendor links, whatever the scheme's case.
    assert _clean_url("http://example.com/fw.bin") == "http://example.com/fw.bin"
    assert _clean_url("HTTPS://example.com/fw.zip") == "HTTPS://example.com/fw.zip"


def test_rescraping_corrects_a_stored_date_but_keeps_first_seen():
    """A value written by an older scraper must not be permanent.

    SFC-60 1.11 carried a date three months wrong, and fixing the parser did not
    correct it because the row already existed. created_at stays put -- it is the
    first-seen signal, and for roughly half the catalogue the only date there is.
    """
    from datetime import datetime
    from src.scrapers.base import ScrapedFirmware
    from src.scrapers.service import _refresh_firmware_row

    class Row:
        release_date = datetime(2024, 7, 10)
        download_url = "https://tal-software.com../../bad.zip"
        changelog_raw = None
        created_at = datetime(2026, 9, 9)

    row = Row()
    _refresh_firmware_row(row, ScrapedFirmware(
        version="1.11",
        release_date=datetime(2024, 10, 7),
        download_url=None,
        changelog="Fixed a thing",
    ))

    assert row.release_date == datetime(2024, 10, 7)   # corrected
    assert row.download_url is None                     # malformed value dropped
    assert row.changelog_raw == "Fixed a thing"         # filled in
    assert row.created_at == datetime(2026, 9, 9)       # first-seen untouched


def test_refresh_never_erases_a_date_the_scraper_stopped_reporting():
    """A vendor removing a date should not delete one already recorded."""
    from datetime import datetime
    from src.scrapers.base import ScrapedFirmware
    from src.scrapers.service import _refresh_firmware_row

    class Row:
        release_date = datetime(2022, 6, 13)
        download_url = "https://example.com/a.zip"
        changelog_raw = "original notes"

    row = Row()
    _refresh_firmware_row(row, ScrapedFirmware(version="1.9"))

    assert row.release_date == datetime(2022, 6, 13)
    assert row.download_url == "https://example.com/a.zip"
    assert row.changelog_raw == "original notes"


def _probe_scraper():
    from src.scrapers.base import BaseScraper

    class Probe(BaseScraper):
        manufacturer_name, manufacturer_slug = "Probe", "probe"
        manufacturer_website = "https://example.invalid"

        async def fetch_device_list(self):
            ...

        async def fetch_firmware_versions(self, device_name, firmware_page_url):
            ...

    return Probe()


def test_identical_pages_groups_urls_that_return_the_same_thing():
    """Every dead-URL case in this project is different URLs, one answer.

    Yamaha's eleven product pages and an invented slug all returned the same landing
    page; Elektron's query parameter selected nothing for any product.
    """
    scraper = _probe_scraper()

    shell = "<html><body><p>Firmware / Software Updates</p></body></html>"
    real = "<html><body><p>MODX6 firmware 1.20</p></body></html>"

    scraper._fingerprint("https://e.invalid/a", shell)
    scraper._fingerprint("https://e.invalid/b", shell)
    scraper._fingerprint("https://e.invalid/c", shell)
    scraper._fingerprint("https://e.invalid/real", real)

    groups = scraper.identical_pages()

    assert len(groups) == 1
    assert groups[0] == ["https://e.invalid/a", "https://e.invalid/b", "https://e.invalid/c"]


def test_products_sharing_one_url_are_not_flagged():
    """QSC's K.2 range, every Peterson product and all of Steinberg share a URL.

    That is one URL rather than several, so it cannot be a URL shape that stopped
    selecting -- and flagging it would make the check noise.
    """
    scraper = _probe_scraper()

    page = "<html><body><p>shared support page</p></body></html>"
    for _ in range(5):
        scraper._fingerprint("https://e.invalid/support", page)

    assert scraper.identical_pages() == []


def test_fingerprint_ignores_a_per_request_token():
    """Elektron's pages differ only by an injected timestamp of constant length.

        window.__wc_fb_page_generated = 1789238504;

    Hashing the raw body makes eleven copies of one page look like eleven different
    pages -- exactly the case this exists to catch. Scripts are stripped first.
    """
    scraper = _probe_scraper()

    first = "<html><head><script>window.__wc_fb_page_generated = 1789238504;</script></head><body><p>same</p></body></html>"
    second = "<html><head><script>window.__wc_fb_page_generated = 1789239134;</script></head><body><p>same</p></body></html>"

    scraper._fingerprint("https://e.invalid/one", first)
    scraper._fingerprint("https://e.invalid/two", second)

    assert len(scraper.identical_pages()) == 1


def test_fingerprint_failure_never_breaks_a_fetch():
    """The fingerprint is diagnostic, so taking one must not affect the result."""
    scraper = _probe_scraper()

    def explode(_html):
        raise ValueError("parser fell over")

    scraper.parse_html = explode
    scraper._fingerprint("https://e.invalid/x", "<html></html>")  # must not raise

    assert scraper.identical_pages() == []


def test_refresh_always_stamps_last_seen_but_never_created_at():
    """last_seen_at answers whether the vendor still lists it, so it is always set.

    The other fields answer what a release is and only fill or correct. created_at is
    the first-seen signal and the only date at all for roughly half the catalogue,
    so it is never rewritten.
    """
    from src.scrapers.base import ScrapedFirmware
    from src.scrapers.service import _refresh_firmware_row

    class Row:
        release_date = datetime(2020, 1, 1)
        download_url = None
        changelog_raw = None
        created_at = datetime(2026, 9, 9)
        last_seen_at = datetime(2026, 9, 9)

    row = Row()
    before = datetime.utcnow()
    _refresh_firmware_row(row, ScrapedFirmware(version="1.0"))

    assert row.last_seen_at >= before
    assert row.created_at == datetime(2026, 9, 9)
    # A scrape reporting no date must still not erase the stored one.
    assert row.release_date == datetime(2020, 1, 1)


@pytest.mark.asyncio
async def test_a_version_the_vendor_drops_stops_being_stamped():
    """This is the whole point: a withdrawn version looks identical without it.

    Scrape twice, the second time without one of the versions, and only the version
    still on the vendor's page should have a fresh last_seen_at.
    """
    from sqlalchemy import select
    from src.devices import service as ds
    from src.devices.models import DeviceCategory, FirmwareVersion
    from src.devices.schemas import DeviceModelCreate, ManufacturerCreate
    from src.scrapers.base import ScrapedFirmware
    from src.scrapers.service import sync_firmware_for_device

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(db, ManufacturerCreate(name="Withdraw Co", slug="withdrawco"))
        model = await ds.create_device_model(db, DeviceModelCreate(
            manufacturer_id=mfr.id, name="Box", category=DeviceCategory.OTHER,
        ))

        await sync_firmware_for_device(db, model.id, [
            ScrapedFirmware(version="1.0"), ScrapedFirmware(version="2.0"),
        ])
        await db.commit()

        rows = (await db.execute(select(FirmwareVersion))).scalars().all()
        original = {r.version: r.last_seen_at for r in rows}

        # The vendor pulls 1.0 and keeps 2.0.
        await sync_firmware_for_device(db, model.id, [ScrapedFirmware(version="2.0")])
        await db.commit()

        rows = (await db.execute(select(FirmwareVersion))).scalars().all()
        after = {r.version: r.last_seen_at for r in rows}

    # The withdrawn version is still stored -- it did happen -- but was not confirmed.
    assert set(after) == {"1.0", "2.0"}
    assert after["1.0"] == original["1.0"]
    assert after["2.0"] >= original["2.0"]


@pytest.mark.asyncio
async def test_a_version_always_beats_the_flag(client):
    """A vendor that starts publishing needs nothing cleared.

    The flag explains an absence. If a version arrives while the flag is still set,
    showing "not published" next to a real version would be the worst of both.
    """
    import re

    from src.devices import service as ds
    from src.devices.models import FirmwareAvailability
    from src.devices.schemas import FirmwareVersionCreate

    model = await _seed_unversioned("Relenting", "relentco", FirmwareAvailability.NOT_PUBLISHED)
    async with test_session_maker() as db:
        await ds.create_firmware_version(db, FirmwareVersionCreate(
            device_model_id=model.id, version="1.0.0", is_latest=True,
        ))

    html = (await client.get("/catalog")).text
    row = re.search(r"<tr[^>]*>(?:(?!</tr>).)*Relenting Box.*?</tr>", html, re.S).group(0)

    assert "1.0.0" in row
    assert "not published" not in row


@pytest.mark.asyncio
async def test_sync_can_clear_an_availability_it_set_before():
    """Revisable in both directions, unlike the URLs beside it.

    A scraper that decides a vendor does publish after all has to be able to take the
    flag off, or the first run's reading outlives the finding that corrected it.
    """
    from src.devices import service as ds
    from src.devices.models import DeviceModel, FirmwareAvailability
    from src.devices.schemas import ManufacturerCreate
    from src.scrapers.base import ScrapedDevice
    from src.scrapers.service import sync_devices
    from sqlalchemy import select as sa_select

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(db, ManufacturerCreate(name="Revise", slug="reviseco"))
        mfr_id = mfr.id

        await sync_devices(db, mfr_id, [ScrapedDevice(
            name="Box", category="audio_interface", firmware_availability="not_published",
        )])
        stored = (await db.execute(
            sa_select(DeviceModel).where(DeviceModel.manufacturer_id == mfr_id)
        )).scalars().first()
        assert stored.firmware_availability == FirmwareAvailability.NOT_PUBLISHED

        await sync_devices(db, mfr_id, [ScrapedDevice(
            name="Box", category="audio_interface", firmware_availability=None,
        )])
        await db.refresh(stored)
        assert stored.firmware_availability is None


@pytest.mark.asyncio
async def test_scrape_separates_explained_absences_from_unexplained():
    """The point of the field. devices_without_firmware carries 95 products on every
    sweep, so a product that went silent this morning joins a crowd nobody reads.
    """
    from src.devices import service as ds
    from src.devices.models import DeviceCategory
    from src.devices.schemas import DeviceModelCreate, ManufacturerCreate
    from src.scrapers import service as ss

    def slugify(value):
        return value.lower().replace(" ", "-")

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(db, ManufacturerCreate(name="Split", slug="splitco"))
        for name, availability in (("Known Silent", "not_published"), ("Suddenly Silent", None)):
            await ds.create_device_model(db, DeviceModelCreate(
                manufacturer_id=mfr.id, name=name, category=DeviceCategory.OTHER,
                firmware_page_url=f"https://split.example.com/{slugify(name)}",
                firmware_availability=availability,
            ))

    from src.scrapers.base import ScrapedDevice, ScraperResult
    from src.scrapers.registry import ScraperRegistry

    from src.scrapers.base import BaseScraper

    # Subclassed rather than duck-typed: the service also calls identical_pages and
    # close, and a hand-rolled stub silently returns an error summary when it misses
    # one of them.
    class Stub(BaseScraper):
        manufacturer_name = "Split"
        manufacturer_slug = "splitco"
        manufacturer_website = "https://split.example.com"

        async def fetch_device_list(self):
            return ScraperResult(success=True, devices=[
                # A firmware_page_url is required: the service only fetches devices
                # that have one, so a device without it is never even attempted.
                ScrapedDevice(name="Known Silent", category="other",
                              firmware_page_url="https://split.example.com/known",
                              firmware_availability="not_published"),
                ScrapedDevice(name="Suddenly Silent", category="other",
                              firmware_page_url="https://split.example.com/sudden"),
            ])

        async def fetch_firmware_versions(self, name, url):
            return ScraperResult(success=True, firmware_versions=[])

    # The registry holds class-level state shared across tests in this process, so the
    # stub is put back the way it was found.
    original = ScraperRegistry.create
    ScraperRegistry.create = staticmethod(
        lambda slug: Stub() if slug == "splitco" else original(slug)
    )
    try:
        async with test_session_maker() as db:
            summary = await ss.scrape_manufacturer(db, "splitco")
    finally:
        ScraperRegistry.create = original

    assert sorted(summary["devices_without_firmware"]) == ["Known Silent", "Suddenly Silent"]
    assert summary["devices_unexplained"] == ["Suddenly Silent"]


@pytest.mark.asyncio
async def test_scrape_routes_not_checked_away_from_unexplained():
    """A deliberate skip is not an absence, and must not land in either absence list."""
    from src.devices import service as ds
    from src.devices.models import DeviceCategory
    from src.devices.schemas import DeviceModelCreate, ManufacturerCreate
    from src.scrapers import service as ss
    from src.scrapers.base import BaseScraper, ScrapedDevice, ScraperResult
    from src.scrapers.registry import ScraperRegistry

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(
            db, ManufacturerCreate(name="Batched", slug="batchedco")
        )
        for name in ("Checked", "Skipped"):
            await ds.create_device_model(db, DeviceModelCreate(
                manufacturer_id=mfr.id, name=name, category=DeviceCategory.OTHER,
                firmware_page_url=f"https://batched.example.com/{name.lower()}",
            ))

    class Stub(BaseScraper):
        manufacturer_name = "Batched"
        manufacturer_slug = "batchedco"
        manufacturer_website = "https://batched.example.com"

        async def fetch_device_list(self):
            return ScraperResult(success=True, devices=[ScrapedDevice(
                name="Checked", category="other",
                firmware_page_url="https://batched.example.com/checked",
            )])

        async def fetch_firmware_versions(self, name, url):
            if name == "Skipped":
                return ScraperResult(success=True, not_checked=True)
            return ScraperResult(success=True, firmware_versions=[])

    original = ScraperRegistry.create
    ScraperRegistry.create = staticmethod(
        lambda slug: Stub() if slug == "batchedco" else original(slug)
    )
    try:
        async with test_session_maker() as db:
            summary = await ss.scrape_manufacturer(db, "batchedco")
    finally:
        ScraperRegistry.create = original

    assert summary["devices_not_checked"] == ["Skipped"]
    assert summary["devices_without_firmware"] == ["Checked"]
    assert summary["devices_unexplained"] == ["Checked"]
    assert "Skipped" not in summary["devices_unexplained"]
