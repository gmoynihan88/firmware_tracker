"""One template environment, with cache-busting for static assets.

The stylesheet link used to carry a hand-written `?v=6`. A number someone has to
remember to bump is a number that drifts: the CSS changed repeatedly without it
moving, so browsers kept serving a cached copy and the changes appeared not to have
happened. The version is now derived from the file itself.
"""
import hashlib
from functools import lru_cache
from pathlib import Path

from fastapi.templating import Jinja2Templates

from src.config import get_settings

settings = get_settings()


@lru_cache(maxsize=64)
def _digest(path: str, fingerprint: tuple) -> str:
    """Hash a file's contents. Keyed on the fingerprint so it re-reads when it changes."""
    del fingerprint  # only present to key the cache
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:10]


def asset_version(relative_path: str) -> str:
    """A short content hash for a file under static/, for use as a query string.

    Recomputed whenever the file's size or mtime changes, so editing CSS takes effect
    without restarting -- uvicorn's reloader only watches Python files, so a
    version captured at import would go stale exactly when it matters.
    """
    path = settings.static_dir / relative_path
    try:
        stat = path.stat()
    except OSError:
        # A missing asset should not break rendering; the link just goes unversioned.
        return "0"
    return _digest(str(path), (stat.st_mtime_ns, stat.st_size))


templates = Jinja2Templates(directory=str(settings.templates_dir))
templates.env.globals["asset_version"] = asset_version
