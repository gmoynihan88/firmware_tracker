"""Fail if any scraper plugin cannot be imported with the runtime dependencies alone.

`ScraperRegistry` discovers plugins with pkgutil, logs a failure to load, and carries on.
So a plugin whose import raises does not break anything -- it vanishes, the registry
agrees with itself, and every slug assertion in the test suite still passes.

That is how production ran 90 scrapers against 91 in development for weeks: ikmultimedia
imported `packaging`, which pytest pulls into the dev lock but the Docker image never
installs. One line per task start said so, and nothing was watching.

Run this with only `requirements.txt` installed -- which is exactly what the image
installs -- and it turns that silence into a non-zero exit:

    pip install --require-hashes -r requirements.txt
    python scripts/check_runtime_imports.py

Comparing counts rather than names is deliberate: a plugin's slug need not match its
filename, so the shortfall is what is reportable, not which name is missing.
"""

import sys
from pathlib import Path

PLUGINS = Path(__file__).resolve().parent.parent / "src" / "scrapers" / "plugins"


def main() -> int:
    sys.path.insert(0, str(PLUGINS.parent.parent.parent))
    from src.scrapers.registry import ScraperRegistry

    files = {path.stem for path in PLUGINS.glob("*.py") if path.stem != "__init__"}
    registered = set(ScraperRegistry.list_available())

    print(f"{len(files)} plugin files, {len(registered)} registered")

    if len(registered) == len(files):
        return 0

    print(
        f"\n{len(files) - len(registered)} plugin(s) failed to import under the runtime "
        f"dependencies. The registry logs each one at ERROR as it happens -- re-run with "
        f"the logging visible to see which, and check whether the import belongs in "
        f"requirements.txt or should be removed from the plugin.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
