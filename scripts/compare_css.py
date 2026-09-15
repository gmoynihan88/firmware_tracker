"""Render every page on two checkouts and diff each element's computed style.

For any change that should not alter how the site looks -- splitting or reordering
stylesheets, renaming classes, restructuring templates -- this is the check that sees
the cascade. Splitting style.css first loaded `.section-header h2` before
`.detail-section h2`, which changed every heading on the device page; all 520 tests
passed. This found it.

    .venv/bin/python scripts/compare_css.py                      # working tree vs main
    .venv/bin/python scripts/compare_css.py --ref v0.6.0         # vs a tag or commit
    .venv/bin/python scripts/compare_css.py --pages / /catalog

REF is checked out into a temporary worktree. The database is copied once, so both
sides render the same rows, and each checkout is served twice on free ports: open,
and with authentication on, because /login only renders when auth is configured.
Chromium loads every page at 1280px and 390px on both and compares computed styles
element by element. Exits 1 on any difference.

Noise it removes, so that a difference is a difference:

- Animations and transitions are switched off on both sides -- the notification
  badge pulses forever, and never settles into the same frame twice.
- Property names are sorted before comparing. Custom properties enumerate in
  declaration order, which moving rules between files changes.
- Fonts have loaded, and a page is re-read until two snapshots agree.

What it cannot see: :hover, :focus, and any state reached by interaction other than
the catalog's version-history dialog, which it opens. For those, read the rules whose
relative order the change flips (same specificity, same element), and check whether
any template element carries both classes.

Needs Playwright's Chromium (`playwright install chromium`), which CI does not have,
so this is a local check and a PR description line, not a test.
"""

import argparse
import asyncio
import contextlib
import os
import pathlib
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from typing import Dict, List, Optional, Tuple

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATABASE = ROOT / "firmware_tracker.db"
WIDTHS = [(1280, 900), (390, 844)]
DIALOG = "#dialog"  # a page suffix: open the first version-history dialog before reading styles

SNAPSHOT_JS = """() => {
  const els = [document.body, ...document.body.querySelectorAll('*')];
  return els.map(el => {
    const cs = getComputedStyle(el);
    const names = [];
    for (let i = 0; i < cs.length; i++) names.push(cs[i]);
    names.sort();
    let s = '';
    for (const n of names) s += n + ':' + cs.getPropertyValue(n) + ';';
    let h = 2166136261;
    for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
    const cls = typeof el.className === 'string' ? el.className.trim().split(/\\s+/).slice(0, 2).join('.') : '';
    return [el.tagName.toLowerCase() + (cls ? '.' + cls : ''), h >>> 0];
  });
}"""

STYLE_JS = """(index) => {
  const el = [document.body, ...document.body.querySelectorAll('*')][index];
  const cs = getComputedStyle(el);
  const out = {};
  for (let i = 0; i < cs.length; i++) out[cs[i]] = cs.getPropertyValue(cs[i]);
  return out;
}"""

NO_MOTION = "*, *::before, *::after { animation: none !important; transition: none !important; }"


def differences(before: Dict[str, str], after: Dict[str, str]) -> Dict[str, Tuple[Optional[str], Optional[str]]]:
    """Properties whose computed value differs, as {property: (before, after)}."""
    return {name: (before.get(name), after.get(name))
            for name in sorted(set(before) | set(after)) if before.get(name) != after.get(name)}


def default_pages(device_id: Optional[int]) -> List[str]:
    pages = ["/", "/catalog", "/catalog" + DIALOG, "/notifications", "/devices/add"]
    if device_id is not None:
        pages += [f"/devices/{device_id}", f"/devices/{device_id}/edit"]
    return pages


def first_device_id(database: pathlib.Path) -> Optional[int]:
    with contextlib.closing(sqlite3.connect(database)) as db:
        row = db.execute("SELECT min(id) FROM my_devices").fetchone()
    return row[0] if row else None


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_server(checkout: pathlib.Path, database: pathlib.Path, auth: bool, logs: pathlib.Path):
    port = free_port()
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{database}", "NOTIFY_TRANSPORT": "none",
           "SCRAPE_CACHE": "false", "LOG_FILE": "", "AUTH_PASSWORD_HASH": "", "SECRET_KEY": ""}
    env.pop("NTFY_TOPIC", None)
    if auth:
        hashed = subprocess.run(
            [sys.executable, "-c", "import sys; from src.auth.security import hash_password; print(hash_password(sys.argv[1]))",
             secrets.token_hex(8)], cwd=checkout, env=env, capture_output=True, text=True, check=True).stdout.strip()
        env.update(AUTH_PASSWORD_HASH=hashed, SECRET_KEY=secrets.token_hex(32))
    log = open(logs / f"{checkout.name}-{'auth' if auth else 'open'}.log", "w")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.main:app", "--port", str(port), "--log-level", "warning"],
        cwd=checkout, env=env, stdout=log, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    for _ in range(120):
        if process.poll() is not None:
            raise RuntimeError(f"server for {checkout} exited; see {log.name}")
        with contextlib.suppress(Exception):
            urllib.request.urlopen(url + "/health", timeout=1)
            return process, url
        time.sleep(0.5)
    process.terminate()
    raise RuntimeError(f"server for {checkout} never answered; see {log.name}")


async def snapshot(page, url: str):
    await page.goto(url.removesuffix(DIALOG), wait_until="networkidle")
    await page.add_style_tag(content=NO_MOTION)
    if url.endswith(DIALOG):
        await page.locator('[aria-haspopup="dialog"]').first.click()
        await page.wait_for_selector("dialog[open]")
        await page.wait_for_load_state("networkidle")
    await page.evaluate("document.fonts.ready.then(() => true)")
    previous = await page.evaluate(SNAPSHOT_JS)
    for _ in range(6):
        await page.wait_for_timeout(400)
        current = await page.evaluate(SNAPSHOT_JS)
        if current == previous:
            return current
        previous = current
    return current


async def compare(pairs: List[Tuple[str, str, List[str]]], shown: int = 8) -> int:
    from playwright.async_api import async_playwright

    total = 0
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        for width, height in WIDTHS:
            for base_url, new_url, pages in pairs:
                before_page = await browser.new_page(viewport={"width": width, "height": height})
                after_page = await browser.new_page(viewport={"width": width, "height": height})
                for path in pages:
                    before, after = await asyncio.gather(snapshot(before_page, base_url + path),
                                                         snapshot(after_page, new_url + path))
                    if len(before) != len(after):
                        print(f"{width:>4} {path:<24} DOM differs: {len(before)} vs {len(after)} elements")
                        total += 1
                        continue
                    changed = [i for i, (b, a) in enumerate(zip(before, after)) if b[1] != a[1]]
                    print(f"{width:>4} {path:<24} elements={len(before):>6} differing={len(changed)}")
                    total += len(changed)
                    for index in changed[:shown]:
                        diff = differences(await before_page.evaluate(STYLE_JS, index),
                                           await after_page.evaluate(STYLE_JS, index))
                        print(f"       {before[index][0]}: {dict(list(diff.items())[:6])}")
                await before_page.close()
                await after_page.close()
        await browser.close()
    return total


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref", default="main", help="what to compare the working tree against (default: main)")
    parser.add_argument("--pages", nargs="+", help=f"paths to compare; end one with {DIALOG} to open the dialog")
    parser.add_argument("--db", type=pathlib.Path, default=DATABASE, help="database to render (copied first)")
    args = parser.parse_args(argv)

    try:
        import playwright  # noqa: F401
    except ImportError:
        print("Playwright is not installed: pip install -r requirements-dev.txt && playwright install chromium")
        return 2
    if not args.db.exists():
        print(f"No database at {args.db}; run a scrape first, or pass --db")
        return 2

    scratch = pathlib.Path(tempfile.mkdtemp(prefix="compare-css-"))
    worktree = scratch / "ref"
    servers = []
    try:
        subprocess.run(["git", "worktree", "add", "--detach", "--quiet", str(worktree), args.ref],
                       cwd=ROOT, check=True)
        database = scratch / "compare.db"
        shutil.copy(args.db, database)
        pages = args.pages or default_pages(first_device_id(database))

        for checkout in (worktree, ROOT):
            for auth in (False, True):
                servers.append(start_server(checkout, database, auth, scratch))
        (ref_open, ref_auth, new_open, new_auth) = (url for _process, url in servers)

        print(f"Comparing the working tree against {args.ref}")
        pairs = [(ref_open, new_open, [p for p in pages if p != "/login"])]
        if not args.pages or "/login" in args.pages:
            pairs.append((ref_auth, new_auth, ["/login"]))
        total = asyncio.run(compare(pairs))
        print(f"TOTAL differing elements: {total}")
        return 1 if total else 0
    finally:
        for process, _url in servers:
            process.terminate()
        for process, _url in servers:
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=10)
        subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=ROOT,
                       capture_output=True)
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
