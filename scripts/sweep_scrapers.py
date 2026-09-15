"""Scrape every manufacturer, uncached against the live sites, and print one line each.

The end-of-batch check from the scraper-batch skill, which used to be retyped inline
every time. Scrapers run one at a time -- a full sweep takes about 20 minutes, Korg
and Pioneer DJ four or five each -- with the response cache and notifications forced
off. `.env` usually turns the cache on, and a sweep that reads saved HTML proves
nothing about the vendors: the tell is Eventide's 61 pages coming back in 2s.

    .venv/bin/python scripts/sweep_scrapers.py                 # everything
    .venv/bin/python scripts/sweep_scrapers.py korg roland     # just these
    .venv/bin/python scripts/sweep_scrapers.py --skip korg     # all but these

On macOS it re-runs itself under `caffeinate -i`. A sweep that outlives display sleep
loses the network, and thirty scrapers then fail in under a second each, which reads
as mass breakage rather than a sleeping laptop.

Read `created` as well as `ok`: devices created for a vendor already in the database
mean its product names stopped matching, and the old rows are now orphans.

Exits 1 when any scraper is not ok, so it can gate a release.
"""

import argparse
import asyncio
import os
import pathlib
import shutil
import sys
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, List, Optional

ROOT = pathlib.Path(__file__).resolve().parent.parent

# The service's own hard limit is 900s; this only catches a scraper that ignores it.
PER_SCRAPER_TIMEOUT = 950


@dataclass
class Outcome:
    slug: str
    seconds: float
    ok: bool
    devices: Optional[int] = None
    created: int = 0
    failed: int = 0
    detail: str = ""


def outcome_from(slug: str, seconds: float, result: dict) -> Outcome:
    """Condense scrape_manufacturer's result into what a sweep reports."""
    synced = result.get("devices_synced") or {}
    failed = result.get("devices_failed") or []
    ok = bool(result.get("success")) and not failed
    return Outcome(
        slug=slug,
        seconds=seconds,
        ok=ok,
        devices=synced.get("total"),
        created=synced.get("created") or 0,
        failed=len(failed),
        detail="" if ok else str(result.get("error") or failed)[:150],
    )


def format_line(outcome: Outcome) -> str:
    return (f"{outcome.slug:<20} {outcome.seconds:>5.0f}s {'ok  ' if outcome.ok else 'FAIL'} "
            f"devices={outcome.devices} created={outcome.created} failed={outcome.failed} {outcome.detail}").rstrip()


async def run_sweep(
    slugs: List[str],
    scrape: Callable[[str], Awaitable[dict]],
    report: Callable[[str], None] = print,
) -> List[Outcome]:
    """Scrape each slug in turn; an exception or a timeout is a failure, never an abort."""
    outcomes = []
    for slug in slugs:
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(scrape(slug), timeout=PER_SCRAPER_TIMEOUT)
            outcome = outcome_from(slug, time.monotonic() - started, result)
        except Exception as exc:  # noqa: BLE001 -- one vendor's crash must not end the sweep
            outcome = Outcome(slug, time.monotonic() - started, False,
                              detail=f"{type(exc).__name__}: {exc}"[:150])
        outcomes.append(outcome)
        report(format_line(outcome))
    return outcomes


def select(available: List[str], only: List[str], skip: List[str]) -> List[str]:
    unknown = sorted(set(only + skip) - set(available))
    if unknown:
        raise SystemExit(f"Unknown scraper slugs: {', '.join(unknown)}")
    chosen = only or available
    return sorted(slug for slug in chosen if slug not in skip)


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("slugs", nargs="*", help="scrape only these (default: every scraper)")
    parser.add_argument("--skip", nargs="+", default=[], metavar="SLUG", help="leave these out")
    parser.add_argument("--no-caffeinate", action="store_true", help="do not keep the Mac awake")
    args = parser.parse_args(argv)

    if (sys.platform == "darwin" and not args.no_caffeinate and not os.environ.get("SWEEP_CAFFEINATED")
            and shutil.which("caffeinate")):
        env = {**os.environ, "SWEEP_CAFFEINATED": "1"}
        os.execvpe("caffeinate", ["caffeinate", "-i", sys.executable, __file__, *argv], env)

    # Environment variables beat .env, and must be set before src.config is imported.
    os.environ["SCRAPE_CACHE"] = "false"
    os.environ["NOTIFY_TRANSPORT"] = "none"
    os.environ.pop("NTFY_TOPIC", None)
    sys.path.insert(0, str(ROOT))

    from src.database import async_session_maker, init_db
    from src.scrapers import service
    from src.scrapers.registry import ScraperRegistry

    slugs = select(ScraperRegistry.list_available(), args.slugs, args.skip)

    async def scrape(slug: str) -> dict:
        async with async_session_maker() as db:
            return await service.scrape_manufacturer(db, slug)

    async def sweep() -> List[Outcome]:
        await init_db()
        print(f"Sweeping {len(slugs)} scrapers, cache off", flush=True)
        return await run_sweep(slugs, scrape, lambda line: print(line, flush=True))

    started = time.monotonic()
    outcomes = asyncio.run(sweep())
    bad = [o.slug for o in outcomes if not o.ok]
    created = [f"{o.slug} ({o.created})" for o in outcomes if o.created]
    print(f"\n{len(outcomes)} scrapers in {time.monotonic() - started:.0f}s; not ok: {', '.join(bad) or 'none'}")
    if created:
        print(f"created devices -- new products, or names that stopped matching: {', '.join(created)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
