"""The owner-only scrape status page.

This page exists because the scrapers here fail by reporting success. A broken one
returns nothing, records `devices_without_firmware` for its whole catalogue, and looks
identical to a vendor that genuinely publishes none. Every assertion below is about
keeping those cases distinguishable on screen rather than about the page rendering.
"""
import re
from datetime import datetime, timedelta

import pytest

from tests.support import test_session_maker


@pytest.fixture
def public_catalog(auth_enabled):
    """Authentication on, catalogue public -- the live site's configuration."""
    auth_enabled.public_catalog = True
    try:
        yield auth_enabled
    finally:
        auth_enabled.public_catalog = False


async def _vendor(slug, name=None, last_scraped_at=None):
    from src.devices import service as ds
    from src.devices.schemas import ManufacturerCreate

    async with test_session_maker() as db:
        mfr = await ds.create_manufacturer(
            db, ManufacturerCreate(name=name or slug.title(), slug=slug)
        )
        if last_scraped_at is not None:
            mfr.last_scraped_at = last_scraped_at
            db.add(mfr)
            await db.commit()
        return mfr


async def _run(slug, *, success=True, started_at=None, **counts):
    from src.devices.models import ScrapeRun

    async with test_session_maker() as db:
        db.add(
            ScrapeRun(
                scraper_type=slug,
                started_at=started_at or datetime.utcnow(),
                success=success,
                **counts,
            )
        )
        await db.commit()


def _row(html, slug):
    """One vendor's row, so an assertion cannot pass because of a different vendor."""
    for chunk in html.split('<tr class="status-row')[1:]:
        chunk = chunk.split("</tr>")[0]
        if f'class="cell-sub">{slug}</span>' in chunk:
            return chunk
    return None


def _nums(row):
    """The five numeric cells: devices, failed, no firmware, not checked, identical."""
    return [
        re.sub(r"<[^>]+>", "", cell).strip()
        for cell in re.findall(r'<td class="num">(.*?)</td>', row, re.S)
    ]


@pytest.mark.asyncio
async def test_the_status_page_is_owner_only(auth_enabled, client):
    """It names which scrapers are broken, which is about this installation."""
    response = await client.get("/scrape-status", headers={"accept": "text/html"})

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


@pytest.mark.asyncio
async def test_a_public_catalogue_does_not_open_the_status_page(public_catalog, client):
    """The configuration the live site actually runs.

    PUBLIC_CATALOG opens the catalogue and the read-only device APIs. This page sits
    one path away from those and is not catalogue data: it is an operational report on
    this installation. The gate is `PUBLIC_READ_PATHS`, which /scrape-status is
    deliberately absent from -- and absence is only a guarantee while something checks
    it, because adding a path there is a one-line change that looks harmless.
    """
    response = await client.get("/scrape-status", headers={"accept": "text/html"})

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


@pytest.mark.asyncio
async def test_the_owner_sees_it(auth_enabled, client):
    await _vendor("korg", "Korg")
    await client.post("/login", data={"password": "correct horse"})

    response = await client.get("/scrape-status", headers={"accept": "text/html"})

    assert response.status_code == 200
    assert "Scrape Status" in response.text


@pytest.mark.asyncio
async def test_the_three_absences_are_kept_apart_rather_than_summed(client):
    """Three different causes, only one of which is a bug.

    A failure is a broken scraper; "no firmware" is the vendor publishing none, which
    is correct and often permanent; "not checked" is the per-manufacturer budget running
    out mid-run. A single total would move when any of them moved and diagnose none.

    The three seeded values are chosen so that no two of them, and no subset, share a
    sum with anything else on the row -- so a column quietly rendering a total fails
    here rather than looking plausible.
    """
    await _vendor("summy", "Summy Audio")
    await _run(
        "summy",
        devices_total=40,
        devices_failed=3,
        devices_without_firmware=11,
        devices_not_checked=29,
    )

    page = (await client.get("/scrape-status", headers={"accept": "text/html"})).text
    row = _row(page, "summy")
    assert row, "the vendor did not render"

    assert _nums(row) == ["40", "3", "11", "29", "0"]
    assert "43" not in row, "the three absences were summed into one figure"


@pytest.mark.asyncio
async def test_identical_pages_are_surfaced_as_an_alarm(client):
    """The quiet one.

    Different URLs returning byte-identical content means the URL shape probably stopped
    selecting a product. The run still reports success and every device reads as having
    no firmware, so nothing else on this page would show it. It is recorded on every run
    and, until this page, displayed nowhere.
    """
    await _vendor("clonev", "Clone Vendor")
    await _run("clonev", devices_total=9, identical_page_groups=4)

    page = (await client.get("/scrape-status", headers={"accept": "text/html"})).text

    assert "status-alarm" in page, "no alarm raised for identical pages"
    assert _nums(_row(page, "clonev"))[4] == "4"
    assert "needs-attention" in _row(page, "clonev")


@pytest.mark.asyncio
async def test_a_clean_run_raises_no_alarm(client):
    """The other half: an alarm that is always on is not an alarm."""
    await _vendor("cleanv", "Clean Vendor")
    await _run("cleanv", devices_total=9, identical_page_groups=0)

    page = (await client.get("/scrape-status", headers={"accept": "text/html"})).text

    assert "status-alarm" not in page
    assert "needs-attention" not in _row(page, "cleanv")


@pytest.mark.asyncio
async def test_a_run_that_succeeded_while_every_device_failed_is_flagged(client):
    """`success` describes the scrape completing, not the scrape working.

    Six vendors in the live database have exactly this shape -- devices_failed equal to
    devices_total with success = 1 -- and the first version of this page sorted all six
    in with the healthy rows, because needs_attention only consulted run.success. A page
    built to surface broken scrapers showing six broken scrapers as fine is worse than
    no page: it manufactures the confidence it exists to withhold.

    The staleness flag does not cover this either. scrape_manufacturer stamps
    last_scraped_at unconditionally after the device loop, so a vendor failing this way
    refreshes its own last-success date on every run.
    """
    await _vendor("allfailv", "All Failed Vendor")
    await _run("allfailv", success=True, devices_total=12, devices_failed=12)

    page = (await client.get("/scrape-status", headers={"accept": "text/html"})).text
    row = _row(page, "allfailv")

    assert row, "the vendor did not render"
    assert "needs-attention" in row, "a run where every device failed read as healthy"
    assert _nums(row)[1] == "12"


@pytest.mark.asyncio
async def test_one_failed_device_is_enough_to_flag(client):
    """Any non-zero count, not only an all-failed run.

    devices_failed means the fetch or parse broke, which is a scraper problem at one
    device or at forty. The cost of "any" would be crying wolf, and the data says it
    does not: partial failures are 10 of 774 recorded runs.
    """
    await _vendor("partialv", "Partial Vendor")
    await _run("partialv", success=True, devices_total=40, devices_failed=1)

    row = _row(
        (await client.get("/scrape-status", headers={"accept": "text/html"})).text,
        "partialv",
    )

    assert "needs-attention" in row
    assert _nums(row)[1] == "1"


@pytest.mark.asyncio
async def test_a_vendor_with_failures_sorts_above_a_clean_one(client):
    """The flag has to reach the ordering, not just the row's styling."""
    await _vendor("aaa-clean", "AAA Clean")
    await _run("aaa-clean", success=True, devices_total=5, devices_failed=0)
    await _vendor("zzz-failed", "ZZZ Failed")
    await _run("zzz-failed", success=True, devices_total=5, devices_failed=5)

    page = (await client.get("/scrape-status", headers={"accept": "text/html"})).text

    assert page.index("zzz-failed") < page.index("aaa-clean")


@pytest.mark.asyncio
async def test_a_failing_vendor_shows_its_last_success_and_its_failure(client):
    """Why there are two time columns rather than one.

    Filtering to successful runs -- which is what the catalogue's vendor cards do, and
    correctly, for their purpose -- would render this vendor as having last worked on
    the 10th and say nothing more. The whole diagnosis is the pair: it worked then, and
    it is failing now.
    """
    await _vendor("brokev", "Broken Vendor")
    await _run("brokev", success=True, started_at=datetime(2026, 9, 10, 12, 0))
    await _run(
        "brokev",
        success=False,
        started_at=datetime(2026, 9, 15, 12, 0),
        devices_failed=6,
    )

    page = (await client.get("/scrape-status", headers={"accept": "text/html"})).text
    row = _row(page, "brokev")

    assert "2026-09-10" in row, "the last successful run was lost"
    assert "2026-09-15" in row, "the failing run was not shown"
    assert "status-fail" in row
    assert "needs-attention" in row


@pytest.mark.asyncio
async def test_a_vendor_whose_index_died_is_flagged_after_a_real_scrape(client):
    """The two halves together, through the service rather than a seeded row.

    Every other test on this page writes its own ScrapeRun. This one runs the actual
    scrape, because the bug lived in the gap between them: scrape_manufacturer returned
    early on a failed device list without recording anything, so the page read the
    vendor's previous successful run and showed it green. Seeding a row could never have
    caught that -- the row was the thing that did not exist.

    The vendor succeeded yesterday and its index is dead today, which is the shape that
    hid: with no row written, last_success still pointed at yesterday and nothing
    marked it broken.
    """
    from src.scrapers.base import BaseScraper, ScraperResult
    from src.scrapers.registry import ScraperRegistry
    from src.scrapers import service as ss

    class _DeadIndex(BaseScraper):
        manufacturer_name = "Deadindex"
        manufacturer_slug = "deadindex"
        manufacturer_website = "https://dead.example"

        async def fetch_device_list(self) -> ScraperResult:
            return ScraperResult(success=False, error="index page returned 500")

        async def fetch_firmware_versions(self, device_name, firmware_page_url) -> ScraperResult:
            return ScraperResult(success=True, firmware_versions=[])

    ScraperRegistry.register(_DeadIndex)
    try:
        # It worked yesterday, which is what made the failure invisible.
        await _vendor("deadindex", "Deadindex")
        await _run("deadindex", success=True, started_at=datetime(2026, 9, 15, 3, 0),
                   devices_total=12)

        async with test_session_maker() as db:
            await ss.scrape_manufacturer(db, "deadindex")

        page = (await client.get("/scrape-status", headers={"accept": "text/html"})).text
    finally:
        ScraperRegistry._scrapers.pop("deadindex", None)

    row = _row(page, "deadindex")
    assert row, "the vendor did not render"
    assert "needs-attention" in row, "a vendor whose index died still read as healthy"
    assert "status-fail" in row
    # Yesterday's success is still shown -- that pair is the diagnosis.
    assert "2026-09-15" in row


@pytest.mark.asyncio
async def test_the_last_scraped_at_fallback_carries_a_vendor_with_no_runs(client):
    """scrape_runs only goes back to the day that table was added.

    manufacturers.last_scraped_at has been maintained since the beginning, so without
    this every vendor scraped before then reads "never" -- which describes a gap in our
    records rather than anything about the vendor.
    """
    await _vendor("legacyv", "Legacy Vendor", last_scraped_at=datetime(2026, 9, 14, 8, 0))

    page = (await client.get("/scrape-status", headers={"accept": "text/html"})).text
    row = _row(page, "legacyv")

    assert "2026-09-14" in row
    assert "inferred" in row, "a fallback date was presented as an observed run"


@pytest.mark.asyncio
async def test_a_vendor_that_has_never_run_says_so(client):
    """The case a scrape_runs-driven page cannot show at all."""
    await _vendor("neverv", "Never Vendor")

    page = (await client.get("/scrape-status", headers={"accept": "text/html"})).text
    row = _row(page, "neverv")

    assert "never" in row
    assert "needs-attention" in row
    # No run means no counts to report, and a zero would claim a run happened.
    assert _nums(row) == ["—", "—", "—", "—", "—"]


@pytest.mark.asyncio
async def test_run_rows_that_are_not_vendors_are_not_listed(client):
    """The live database holds two scraper_type values that are not scrapers.

    One is a stray 'nope-not-a-scraper'; the other is a single string of 21 slugs joined
    by spaces. Both record a failure, so a page driven off scrape_runs would headline two
    failing vendors that do not exist. Iterating manufacturers excludes them for free --
    this pins that it stays that way.
    """
    await _vendor("realv", "Real Vendor")
    await _run("nope-not-a-scraper", success=False)
    await _run("korg novation roland", success=False)

    page = (await client.get("/scrape-status", headers={"accept": "text/html"})).text

    assert _row(page, "realv")
    assert "nope-not-a-scraper" not in page
    assert "korg novation roland" not in page


@pytest.mark.asyncio
async def test_a_stale_vendor_is_flagged_against_the_configured_interval(client):
    """Two missed runs is a pattern; one is a Spot interruption or a slow vendor.

    Derived from scrape_interval_hours rather than hardcoded, so changing the schedule
    does not quietly turn every vendor amber.
    """
    from src.config import get_settings

    interval = get_settings().scrape_interval_hours
    await _vendor("stalev", "Stale Vendor")
    await _run("stalev", started_at=datetime.utcnow() - timedelta(hours=interval * 3))
    await _vendor("freshv", "Fresh Vendor")
    await _run("freshv", started_at=datetime.utcnow())

    page = (await client.get("/scrape-status", headers={"accept": "text/html"})).text

    assert "status-stale" in _row(page, "stalev")
    assert "needs-attention" in _row(page, "stalev")
    assert "status-stale" not in _row(page, "freshv")


@pytest.mark.asyncio
async def test_vendors_needing_attention_sort_above_healthy_ones(client):
    """Ninety-one rows is too many to scan for the two that matter."""
    await _vendor("aaa-healthy", "AAA Healthy")
    await _run("aaa-healthy", devices_total=5)
    await _vendor("zzz-broken", "ZZZ Broken")
    await _run("zzz-broken", success=False, started_at=datetime.utcnow())

    page = (await client.get("/scrape-status", headers={"accept": "text/html"})).text

    assert page.index("zzz-broken") < page.index("aaa-healthy"), (
        "alphabetical order won over the vendor that needs looking at"
    )


@pytest.mark.asyncio
async def test_the_navigation_links_it_only_for_the_owner(public_catalog, client):
    anonymous = (await client.get("/catalog", headers={"accept": "text/html"})).text
    assert 'href="/scrape-status"' not in anonymous

    await client.post("/login", data={"password": "correct horse"})
    owner = (await client.get("/catalog", headers={"accept": "text/html"})).text
    assert 'href="/scrape-status"' in owner
