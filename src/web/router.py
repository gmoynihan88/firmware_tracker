from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from urllib.parse import urlencode

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from src.database import get_db
from src.devices.models import (
    DeviceCategory,
    DeviceModel,
    FirmwareVersion,
    Manufacturer,
    MyDevice,
    ScrapeRun,
)
from src.config import get_settings
from src.devices import service as device_service
from src.devices.schemas import MyDeviceCreate, MyDeviceUpdate
from src.notifications.reconcile import is_behind
from src.scrapers.registry import ScraperRegistry
from src.scrapers import service as scraper_service

settings = get_settings()
# Shared environment, so asset_version() is available to every template.
from src.templating import templates  # noqa: E402

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    """Main dashboard showing all tracked devices and their firmware status."""
    my_devices = await device_service.get_my_devices(db)
    unread_count = await device_service.get_unread_count(db)

    # Enrich devices with firmware status
    devices_with_status = []
    for device in my_devices:
        latest = await device_service.get_latest_firmware(db, device.device_model_id)
        firmware_count = await device_service.get_firmware_version_count(db, device.device_model_id)

        # Three states, not two. A device with no recorded installed version is not
        # behind, it is unrecorded -- previously these were shown as "Update
        # Available", which is a guess, and the same numeric comparison the
        # notification paths use is applied here so the dashboard cannot disagree
        # with what gets notified.
        if not device.current_firmware_version:
            status = "unknown"
        elif latest and is_behind(device.current_firmware_version, latest.version):
            status = "update"
        else:
            status = "current"

        devices_with_status.append({
            "device": device,
            "latest_firmware": latest,
            "status": status,
            "has_update": status == "update",
            "firmware_count": firmware_count,
        })

    return templates.TemplateResponse(
        request,
        name="dashboard.html",
        context={
            "devices": devices_with_status,
            "unread_count": unread_count,
        },
    )


@router.get("/devices/add", response_class=HTMLResponse)
async def add_device_page(
    request: Request,
    model_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    """Page to add a new device to track.

    The catalogue's Track button links here with `?model_id=`, and until this read
    it the form opened empty: clicking Track on Digitakt II dropped you at "Select a
    manufacturer first" with 755 devices to find it among, which is worse than no
    link at all because it looks like it did something.
    """
    manufacturers = await device_service.get_manufacturers(db)
    device_models = await device_service.get_device_models(db)
    unread_count = await device_service.get_unread_count(db)

    # Resolved rather than trusted: a stale bookmark or a deleted model would
    # otherwise pre-select an id that no longer exists and fail on submit.
    selected = await device_service.get_device_model(db, model_id) if model_id else None

    return templates.TemplateResponse(
        request,
        name="add_device.html",
        context={
            "manufacturers": manufacturers,
            "device_models": device_models,
            "unread_count": unread_count,
            "selected_model": selected,
            "selected_models": (
                [m for m in device_models if m.manufacturer_id == selected.manufacturer_id]
                if selected else []
            ),
        },
    )


@router.post("/devices/add")
async def add_device(
    request: Request,
    device_model_id: int = Form(...),
    nickname: Optional[str] = Form(None),
    current_firmware_version: Optional[str] = Form(None),
    notify_on_update: bool = Form(True),
    notes: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Handle adding a new device."""
    device_model = await device_service.get_device_model(db, device_model_id)
    if not device_model:
        raise HTTPException(status_code=404, detail="Device model not found")

    await device_service.create_my_device(
        db,
        MyDeviceCreate(
            device_model_id=device_model_id,
            nickname=nickname or None,
            current_firmware_version=current_firmware_version or None,
            notify_on_update=notify_on_update,
            notes=notes or None,
        ),
    )
    return RedirectResponse(url="/", status_code=303)


@router.get("/devices/{device_id}", response_class=HTMLResponse)
async def device_detail(
    request: Request, device_id: int, db: AsyncSession = Depends(get_db)
):
    """Device detail page with firmware history."""
    device = await device_service.get_my_device(db, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    firmware_versions = await device_service.get_firmware_versions(
        db, device.device_model_id
    )
    unread_count = await device_service.get_unread_count(db)

    return templates.TemplateResponse(
        request,
        name="device_detail.html",
        context={
            "device": device,
            "firmware_versions": firmware_versions,
            "unread_count": unread_count,
        },
    )


@router.get("/devices/{device_id}/edit", response_class=HTMLResponse)
async def edit_device_page(
    request: Request, device_id: int, db: AsyncSession = Depends(get_db)
):
    """Edit device page."""
    device = await device_service.get_my_device(db, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    firmware_versions = await device_service.get_firmware_versions(
        db, device.device_model_id
    )
    unread_count = await device_service.get_unread_count(db)

    return templates.TemplateResponse(
        request,
        name="edit_device.html",
        context={
            "device": device,
            "firmware_versions": firmware_versions,
            "unread_count": unread_count,
        },
    )


@router.post("/devices/{device_id}/edit")
async def edit_device(
    device_id: int,
    nickname: Optional[str] = Form(None),
    current_firmware_version: Optional[str] = Form(None),
    notify_on_update: bool = Form(False),
    notes: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Handle device update."""
    device = await device_service.update_my_device(
        db,
        device_id,
        MyDeviceUpdate(
            nickname=nickname or None,
            current_firmware_version=current_firmware_version or None,
            notify_on_update=notify_on_update,
            notes=notes or None,
        ),
    )
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return RedirectResponse(url=f"/devices/{device_id}", status_code=303)


@router.post("/devices/{device_id}/delete")
async def delete_device(device_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a device."""
    deleted = await device_service.delete_my_device(db, device_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Device not found")
    return RedirectResponse(url="/", status_code=303)


@router.get("/notifications", response_class=HTMLResponse)
async def notifications_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Notifications page."""
    notifications = await device_service.get_notifications(db)
    unread_count = await device_service.get_unread_count(db)

    return templates.TemplateResponse(
        request,
        name="notifications.html",
        context={
            "notifications": notifications,
            "unread_count": unread_count,
        },
    )


@router.post("/notifications/{notification_id}/read")
async def mark_read(notification_id: int, db: AsyncSession = Depends(get_db)):
    """Mark a notification as read (HTMX endpoint)."""
    await device_service.mark_notification_read(db, notification_id)
    return HTMLResponse(content="", status_code=200)


@router.post("/notifications/read-all")
async def mark_all_read(db: AsyncSession = Depends(get_db)):
    """Mark all notifications as read."""
    await device_service.mark_all_notifications_read(db)
    return RedirectResponse(url="/notifications", status_code=303)


CATALOG_PAGE_SIZES = (25, 50, 100)
CATALOG_DEFAULT_SIZE = 50
CATALOG_DEFAULT_SORT = "product"


@router.get("/catalog", response_class=HTMLResponse)
async def catalog_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    q: str = "",
    vendor: str = "",
    kind: str = "",
    hide_tracked: bool = False,
    sort: str = CATALOG_DEFAULT_SORT,
    direction: str = "asc",
    page: int = 1,
    size: int = CATALOG_DEFAULT_SIZE,
):
    """Device catalog browsing page, one page of rows at a time.

    Filtering, sorting and paging all happen in SQL. They used to happen in the
    browser, which meant every one of the catalogue's products had to be in the HTML
    before any of them could be filtered -- a 1.8MB page to show fifty rows.
    """
    # With PUBLIC_CATALOG on, this is the one page an anonymous visitor may read. The
    # products are public facts about other people's gear; which of them someone owns,
    # and what they have been notified about, is not -- so neither is fetched at all,
    # rather than fetched and hidden in the template.
    authenticated = getattr(request.state, "authenticated", True)

    manufacturers = await device_service.get_manufacturers(db)
    unread_count = await device_service.get_unread_count(db) if authenticated else 0

    # Every parameter is clamped to something renderable rather than rejected. These
    # arrive from a bookmarked or shared URL as often as from the form, and answering
    # 422 to size=17 is a worse answer than fifty rows.
    if size not in CATALOG_PAGE_SIZES:
        size = CATALOG_DEFAULT_SIZE
    if direction not in ("asc", "desc"):
        direction = "asc"
    if kind not in ("hardware", "software"):
        kind = ""
    if vendor not in {maker.slug for maker in manufacturers}:
        vendor = ""
    q = q.strip()

    # One row per model from each, so neither join can multiply the result.
    latest = (
        select(
            FirmwareVersion.device_model_id.label("model_id"),
            FirmwareVersion.release_date,
            FirmwareVersion.version_sort_key,
        )
        .where(FirmwareVersion.is_latest.is_(True))
        .subquery()
    )
    counts = (
        select(
            FirmwareVersion.device_model_id.label("model_id"),
            func.count(FirmwareVersion.id).label("total"),
        )
        .group_by(FirmwareVersion.device_model_id)
        .subquery()
    )

    listing = (
        select(DeviceModel)
        .options(selectinload(DeviceModel.manufacturer))
        .join(Manufacturer, Manufacturer.id == DeviceModel.manufacturer_id)
        .outerjoin(latest, latest.c.model_id == DeviceModel.id)
        .outerjoin(counts, counts.c.model_id == DeviceModel.id)
    )

    if q:
        term = f"%{q.lower()}%"
        listing = listing.where(
            or_(
                func.lower(DeviceModel.name).like(term),
                func.lower(Manufacturer.name).like(term),
            )
        )
    # Software is the VST_PLUGIN category and hardware is everything else, the same
    # split the rows themselves are marked with.
    if kind == "software":
        listing = listing.where(DeviceModel.category == DeviceCategory.VST_PLUGIN)
    elif kind == "hardware":
        listing = listing.where(DeviceModel.category != DeviceCategory.VST_PLUGIN)
    if vendor:
        listing = listing.where(Manufacturer.slug == vendor)
    # Owner-only, and forced off for a visitor: an anonymous page has no tracked
    # devices to hide and no checkbox offering to. Rewriting the flag rather than
    # ignoring it keeps the URLs the page builds from agreeing with what it rendered.
    if hide_tracked and authenticated:
        listing = listing.where(DeviceModel.id.notin_(select(MyDevice.device_model_id)))
    else:
        hide_tracked = False

    sortable = {
        "vendor": Manufacturer.name,
        "product": DeviceModel.name,
        "type": DeviceModel.category,
        # The stored key, not the version text: it is parse_version's comparison in a
        # form SQL can order by, so 1.11 ranks above 1.9 here exactly as it does when
        # the scraper decides which row is_latest. See src/devices/versions.py.
        "latest": latest.c.version_sort_key,
        "others": func.coalesce(counts.c.total, 0),
        "released": latest.c.release_date,
    }
    if sort not in sortable:
        sort = CATALOG_DEFAULT_SORT
    column = sortable[sort]
    listing = listing.order_by(
        # A product with no version sorts last whichever way the column points, which
        # is what the old browser-side sort did with its em-dash. Letting them fall
        # into the middle of a descending page would read as "the oldest releases".
        column.is_(None),
        column.desc() if direction == "desc" else column.asc(),
        # A deterministic tie-break, or LIMIT/OFFSET can show a row on one page and
        # skip it on the next: most of this table ties on category or on having no
        # release date at all.
        DeviceModel.name,
        DeviceModel.id,
    )

    total = (
        await db.execute(
            select(func.count()).select_from(listing.order_by(None).subquery())
        )
    ).scalar_one()
    # Whether the catalogue is empty is a different question from whether this filter
    # matched anything, and the page says different things about them.
    total_devices = (await db.execute(select(func.count(DeviceModel.id)))).scalar_one()

    pages = max(1, -(-total // size))
    page = min(max(1, page), pages)
    first_row = (page - 1) * size + 1 if total else 0
    last_row = min(page * size, total)

    device_models = (
        (await db.execute(listing.limit(size).offset((page - 1) * size))).scalars().all()
    )
    page_ids = [model.id for model in device_models]

    def catalog_url(**overrides) -> str:
        """This view with some parameters changed, and defaults left out.

        Leaving defaults out is not tidiness: CloudFront keys this page's cache on the
        whole query string, so a link spelling out every default would be a second
        cache entry for the page the reader is already on.
        """
        params = {
            "q": q,
            "vendor": vendor,
            "kind": kind,
            "hide_tracked": hide_tracked,
            "sort": sort,
            "direction": direction,
            "page": page,
            "size": size,
        }
        params.update(overrides)
        defaults = {
            "q": "",
            "vendor": "",
            "kind": "",
            "hide_tracked": False,
            "sort": CATALOG_DEFAULT_SORT,
            "direction": "asc",
            "page": 1,
            "size": CATALOG_DEFAULT_SIZE,
        }
        query = urlencode(
            {key: value for key, value in params.items() if value != defaults[key]}
        )
        return f"/catalog?{query}" if query else "/catalog"

    # The import panel is the owner's, and the template renders it behind the same check
    # as this one. So these three queries and the list they built existed only to fill
    # markup a visitor never receives -- on /catalog, which is the public, cached, most
    # requested page here. An anonymous request now runs none of them.
    available_scrapers = []
    if authenticated:
        # The registry lists slugs, and the template used to title-case them, which
        # rendered "Ikmultimedia", "Izotope", "Line6" and "Nativeinstruments". Each
        # scraper carries the vendor's own spelling, so use that.
        device_counts = {
            row[0]: row[1]
            for row in (
                await db.execute(
                    select(Manufacturer.slug, func.count(DeviceModel.id))
                    .join(DeviceModel, DeviceModel.manufacturer_id == Manufacturer.id)
                    .group_by(Manufacturer.slug)
                )
            ).all()
        }

        # Most recent successful run per scraper, so a vendor card can say when it last
        # worked rather than only offering to run again. scrape_runs only goes back to
        # the day that table was added, so manufacturers.last_scraped_at -- maintained
        # since the beginning -- is the fallback. Without it every vendor scraped before
        # then reads "never scraped", which is worse than the gap it describes.
        last_runs = {
            row[0]: row[1]
            for row in (
                await db.execute(
                    select(ScrapeRun.scraper_type, func.max(ScrapeRun.started_at))
                    .where(ScrapeRun.success.is_(True))
                    .group_by(ScrapeRun.scraper_type)
                )
            ).all()
        }

        vendor_rows = (
            await db.execute(
                select(Manufacturer.slug, Manufacturer.website_url, Manufacturer.last_scraped_at)
            )
        ).all()
        websites = {row[0]: row[1] for row in vendor_rows}
        legacy_scraped = {row[0]: row[2] for row in vendor_rows}

        available_scrapers = [
            {
                "slug": slug,
                "name": ScraperRegistry.get(slug).manufacturer_name,
                "device_count": device_counts.get(slug, 0),
                "last_run": last_runs.get(slug) or legacy_scraped.get(slug),
                "website": websites.get(slug) or ScraperRegistry.get(slug).manufacturer_website,
            }
            for slug in sorted(
                ScraperRegistry.list_available(),
                key=lambda s: ScraperRegistry.get(s).manufacturer_name.lower(),
            )
        ]

    # Which models the user already tracks, so the table can say so instead of
    # offering to add a second copy of something they have.
    tracked_model_ids = (
        {row[0] for row in (await db.execute(select(MyDevice.device_model_id))).all()}
        if authenticated
        else set()
    )

    # Latest known version per model, in one query rather than one per row. The
    # release date rides along: 201 of the 303 current versions carry one, and the
    # other 102 are vendors who publish none rather than a date we failed to read.
    # Those render as an em-dash. `created_at` is not substituted -- it is when this
    # tracker first saw the version, which is a different fact, and putting it under
    # a "Released" heading would be the invention this project exists to avoid. The
    # dashboard shows it in its own "Discovered" column instead.
    #
    # Scoped to the rows on this page. Unscoped, these two loaded a row for every
    # version in the database -- 11,207 of them -- to render fifty.
    latest_versions = {
        row.device_model_id: row
        for row in (
            await db.execute(
                select(
                    FirmwareVersion.device_model_id,
                    FirmwareVersion.version,
                    FirmwareVersion.release_date,
                )
                .where(FirmwareVersion.is_latest.is_(True))
                .where(FirmwareVersion.device_model_id.in_(page_ids))
            )
        ).all()
    } if page_ids else {}

    # How many versions each model has, so the table can offer the ones behind the
    # latest. Only the count: the histories run to 5,000 versions with their notes,
    # and each is fetched when someone asks for it.
    version_counts = {
        row[0]: row[1]
        for row in (
            await db.execute(
                select(FirmwareVersion.device_model_id, func.count(FirmwareVersion.id))
                .where(FirmwareVersion.device_model_id.in_(page_ids))
                .group_by(FirmwareVersion.device_model_id)
            )
        ).all()
    } if page_ids else {}

    return templates.TemplateResponse(
        request,
        name="catalog.html",
        context={
            "manufacturers": manufacturers,
            "device_models": device_models,
            "available_scrapers": available_scrapers,
            "tracked_model_ids": tracked_model_ids,
            "latest_versions": latest_versions,
            "version_counts": version_counts,
            "unread_count": unread_count,
            # The current view, for the form, the column headers and the pager.
            "catalog_url": catalog_url,
            "search": q,
            "vendor": vendor,
            "kind": kind,
            "hide_tracked": hide_tracked,
            "sort": sort,
            "direction": direction,
            "page": page,
            "pages": pages,
            "size": size,
            "page_sizes": CATALOG_PAGE_SIZES,
            "total": total,
            "total_devices": total_devices,
            "first_row": first_row,
            "last_row": last_row,
        },
    )


@router.get("/catalog/versions/{model_id}", response_class=HTMLResponse)
async def catalog_version_history(
    request: Request, model_id: int, db: AsyncSession = Depends(get_db)
):
    """Every version of a product except the latest, for the catalog's history popup."""
    names = (
        await db.execute(
            select(DeviceModel.name, Manufacturer.name)
            .join(Manufacturer, DeviceModel.manufacturer_id == Manufacturer.id)
            .where(DeviceModel.id == model_id)
        )
    ).first()
    if names is None:
        raise HTTPException(status_code=404, detail="Device model not found")

    # Highest version first, compared as numbers -- the order the device page uses.
    versions = [
        fw for fw in await device_service.get_firmware_versions(db, model_id)
        if not fw.is_latest
    ]
    return templates.TemplateResponse(
        request,
        name="partials/version_history.html",
        context={"product": names[0], "vendor": names[1], "versions": versions},
    )


@router.post("/catalog/scrape/{scraper_type}")
async def scrape_manufacturer(
    request: Request,
    scraper_type: str,
    db: AsyncSession = Depends(get_db),
):
    """Trigger a scrape for a manufacturer (HTMX endpoint)."""
    result = await scraper_service.scrape_manufacturer(db, scraper_type)
    return templates.TemplateResponse(
        request,
        name="partials/scrape_result.html",
        context={"result": result},
    )


@router.get("/scrape-status", response_class=HTMLResponse)
async def scrape_status(request: Request, db: AsyncSession = Depends(get_db)):
    """Owner-only: what every scraper did the last time it ran.

    Deliberately absent from `PUBLIC_READ_PATHS`. The catalogue is public because it
    describes other people's products; this describes *this installation* -- which of
    its scrapers are broken, and how long they have been broken -- so it stays behind
    the password. Nothing here had to be added to make that true: the middleware closes
    everything it is not told to open, which is the safer direction for the default.

    **Two time columns, because they answer different questions.** `last_success` is
    when this vendor's data was last actually refreshed. `last_run` is the most recent
    attempt whatever its outcome, and it is the only one that can show a scraper
    failing *now*: filtering to successful runs -- which is what the catalogue's vendor
    cards do, correctly, for their own purpose -- hides precisely the case this page
    exists to surface. A vendor whose last success was Tuesday and whose last run
    failed this morning looks healthy in one column and broken in the other, and that
    pair is the whole diagnosis.

    **The three absences are kept apart and never summed**, because they have three
    different causes and only one is a bug:

    - `devices_failed` -- the fetch or parse broke. A scraper problem.
    - `devices_without_firmware` -- the page loaded and the product genuinely ships
      none. Correct behaviour, and permanent for some products.
    - `devices_not_checked` -- the per-manufacturer budget ran out before reaching
      them. Not an error, but it means the run was incomplete and the numbers beside
      it describe a subset.

    A total over the three would move when any of them moved and mean nothing when it
    did.

    **Driven off `manufacturers`, not `scrape_runs`.** A vendor that stopped running
    altogether has no recent row, so iterating runs would omit it in silence -- the one
    failure mode most worth catching. Iterating vendors renders it as "never". It also
    keeps junk out: this database holds two `scraper_type` values that are not
    scrapers, a stray `nope-not-a-scraper` and a single string of 21 slugs joined by
    spaces, and both record a failure. A runs-driven page would headline two failing
    vendors that do not exist.
    """
    settings = get_settings()

    # The newest run per vendor regardless of outcome. row_number rather than a
    # max(started_at) join: a join on the maximum returns two rows for a vendor that
    # has two runs sharing a timestamp, which silently duplicates it. Ordering by id
    # as well makes the winner deterministic when that happens.
    ranked = (
        select(
            ScrapeRun.scraper_type,
            ScrapeRun.started_at,
            ScrapeRun.success,
            ScrapeRun.error,
            ScrapeRun.duration_seconds,
            ScrapeRun.devices_total,
            ScrapeRun.devices_failed,
            ScrapeRun.devices_without_firmware,
            ScrapeRun.devices_not_checked,
            ScrapeRun.new_versions,
            ScrapeRun.identical_page_groups,
            func.row_number()
            .over(
                partition_by=ScrapeRun.scraper_type,
                order_by=(ScrapeRun.started_at.desc(), ScrapeRun.id.desc()),
            )
            .label("rank"),
        )
    ).subquery()

    latest_runs = {
        row.scraper_type: row
        for row in (await db.execute(select(ranked).where(ranked.c.rank == 1))).all()
    }

    # Same fallback the catalogue's vendor cards use: scrape_runs only goes back to the
    # day that table was added, so manufacturers.last_scraped_at -- maintained since the
    # beginning -- covers everything scraped before it. Without it most of this column
    # would read "never", which describes the gap in our records rather than the vendor.
    last_success = {
        row[0]: row[1]
        for row in (
            await db.execute(
                select(ScrapeRun.scraper_type, func.max(ScrapeRun.started_at))
                .where(ScrapeRun.success.is_(True))
                .group_by(ScrapeRun.scraper_type)
            )
        ).all()
    }

    vendor_rows = (
        await db.execute(
            select(Manufacturer.slug, Manufacturer.name, Manufacturer.last_scraped_at)
        )
    ).all()

    # Twice the configured interval. One missed run is a Spot interruption or a slow
    # vendor; two is a pattern. Derived from the setting rather than hardcoded, so
    # changing the schedule does not quietly turn every vendor amber.
    stale_after = timedelta(hours=settings.scrape_interval_hours * 2)
    now = datetime.utcnow()

    vendors = []
    for slug, name, legacy_scraped in vendor_rows:
        run = latest_runs.get(slug)
        succeeded_at = last_success.get(slug) or legacy_scraped

        failing = run is not None and not run.success
        never = succeeded_at is None and run is None
        stale = succeeded_at is not None and (now - succeeded_at) > stale_after
        identical = (run.identical_page_groups or 0) if run else 0

        vendors.append(
            {
                "slug": slug,
                "name": name,
                "last_success": succeeded_at,
                # True when the only evidence of a success predates the scrape_runs
                # table, so the template can mark it as inferred rather than observed.
                "success_is_legacy": slug not in last_success and legacy_scraped is not None,
                "run": run,
                "failing": failing,
                "never": never,
                "stale": stale,
                "identical_page_groups": identical,
                "needs_attention": failing or never or stale or identical > 0,
            }
        )

    # Anything needing attention first, then alphabetical. Ninety-one rows is too many
    # to scan for the two that matter, and the ordering is stable for a given state --
    # a row only moves when its condition actually changes.
    vendors.sort(key=lambda v: (not v["needs_attention"], v["name"].lower()))

    return templates.TemplateResponse(
        request,
        name="scrape_status.html",
        context={
            "vendors": vendors,
            "total": len(vendors),
            "attention": sum(1 for v in vendors if v["needs_attention"]),
            "failing": sum(1 for v in vendors if v["failing"]),
            "never": sum(1 for v in vendors if v["never"]),
            "stale": sum(1 for v in vendors if v["stale"]),
            "identical": sum(1 for v in vendors if v["identical_page_groups"] > 0),
            "stale_after_hours": settings.scrape_interval_hours * 2,
            # base.html's nav reads this, and Jinja raises on `undefined > 0` rather
            # than treating it as falsy -- so omitting it 500s the page.
            "unread_count": await device_service.get_unread_count(db),
        },
    )


@router.get("/partials/notification-badge", response_class=HTMLResponse)
async def notification_badge(request: Request, db: AsyncSession = Depends(get_db)):
    """HTMX polling endpoint for notification badge."""
    unread_count = await device_service.get_unread_count(db)
    return templates.TemplateResponse(
        request,
        name="partials/notification_badge.html",
        context={"unread_count": unread_count},
    )


@router.get("/partials/device-models", response_class=HTMLResponse)
async def device_models_partial(
    request: Request,
    manufacturer_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    """HTMX endpoint to load device models for a manufacturer."""
    device_models = []
    if manufacturer_id:
        device_models = await device_service.get_device_models(db, manufacturer_id)
    return templates.TemplateResponse(
        request,
        name="partials/device_models_select.html",
        context={"device_models": device_models},
    )
