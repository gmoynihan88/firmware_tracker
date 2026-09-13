#!/usr/bin/env python3
"""Claude Code status line: scraper-batch progress, then the branch.

    batch 2/10 · Kilohearts · test · 2 merged · next: Goodhertz │ kilohearts-scraper (+1)

Reads `.claude/batch.json`, which the `scraper-batch` skill keeps current. Whether a
vendor is merged is never read from that file: it is derived from `main`, where a
plugin declaring the vendor's `manufacturer_slug` either exists or does not. A
hand-kept merged count would drift the way the README's scraper count did.

The branch carries its commit count ahead of main, because branching from the wrong
branch has stacked PRs here twice and is invisible until review.

Runs on system Python (3.9 on this machine), so no 3.10+ syntax. Must never raise:
a status line that prints a traceback is worse than none.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BATCH = Path(os.environ.get("BATCH_FILE", str(REPO / ".claude" / "batch.json")))
SLUG = re.compile(r'manufacturer_slug\s*=\s*"([^"]+)"')
SEP = " · "


def git(*args):
    try:
        done = subprocess.run(
            ["git", "-C", str(REPO)] + list(args),
            capture_output=True, text=True, timeout=2,
        )
        return done.stdout if done.returncode == 0 else ""
    except Exception:
        return ""


def slugs_on_main():
    """Every manufacturer_slug declared by a plugin on main."""
    out = git("grep", "-h", "manufacturer_slug", "main", "--", "src/scrapers/plugins/")
    return set(SLUG.findall(out))


def batch_segment():
    try:
        batch = json.loads(BATCH.read_text())
    except (OSError, ValueError):
        return None
    vendors = [v for v in batch.get("vendors") or [] if isinstance(v, dict) and v.get("slug")]
    if not vendors:
        return None

    merged = slugs_on_main()
    done = [v for v in vendors if v["slug"] in merged]
    skipped = [v for v in vendors if v["slug"] not in merged and v.get("verdict") == "none"]
    finished = {v["slug"] for v in done + skipped}

    current = batch.get("current") or {}
    active = next(
        (v for v in vendors if v["slug"] == current.get("slug") and v["slug"] not in finished),
        None,
    )
    waiting = [v for v in vendors if v["slug"] not in finished and v is not active]

    parts = ["batch {}/{}".format(len(finished), len(vendors))]
    if active:
        parts.append("{}{}{}".format(active.get("name", active["slug"]), SEP, current.get("step", "?")))
    parts.append("{} merged".format(len(done)))
    if skipped:
        parts.append("{} skipped".format(len(skipped)))
    if waiting:
        parts.append("next: {}".format(waiting[0].get("name", waiting[0]["slug"])))
    elif not active:
        parts.append("complete")
    return SEP.join(parts)


def branch_segment():
    branch = git("branch", "--show-current").strip()
    if not branch:
        return None
    if branch == "main":
        return branch
    ahead = git("rev-list", "--count", "main..HEAD").strip()
    return "{} (+{})".format(branch, ahead) if ahead.isdigit() else branch


def main():
    try:
        sys.stdin.read()  # Claude Code sends session JSON; drain it, nothing here needs it
    except Exception:
        pass
    segments = []
    for build in (batch_segment, branch_segment):
        try:
            segment = build()
        except Exception:
            segment = None
        if segment:
            segments.append(segment)
    print(" │ ".join(segments))


if __name__ == "__main__":
    main()
