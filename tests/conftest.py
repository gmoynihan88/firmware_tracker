"""Test configuration.

The test suite must never deliver a notification. Both notification paths call
get_notifier(get_settings()), and get_settings() reads .env -- so on any machine
with a transport configured, running pytest pushed fixture notifications ("Stub
Synth", "Genuinely Behind") to the developer's real phone.

Environment variables take precedence over .env in pydantic-settings, so setting
this before src.config is imported disables delivery for the whole session.
"""
import os

# Must happen before anything imports src.config and caches its settings.
os.environ["NOTIFY_TRANSPORT"] = "none"
os.environ.pop("NTFY_TOPIC", None)

import pytest  # noqa: E402

from src.config import get_settings  # noqa: E402
from src.notifications.transport import NullNotifier  # noqa: E402


@pytest.fixture(autouse=True)
def never_deliver_notifications(monkeypatch):
    """Belt and braces: force the notifier to Null for every test.

    The environment variable above should be enough on its own, but a test that
    builds its own Settings, or a cached settings object created before this module
    was imported, would slip past it. Delivery is a side effect with an external
    destination, so it is worth blocking twice.
    """
    get_settings.cache_clear()

    def _null(*_args, **_kwargs):
        return NullNotifier()

    for module in ("src.scrapers.service", "src.notifications.reconcile"):
        monkeypatch.setattr(f"{module}.get_notifier", _null, raising=True)

    yield
    get_settings.cache_clear()


from httpx import ASGITransport, AsyncClient  # noqa: E402

from src.database import Base, get_db  # noqa: E402
from src.main import app  # noqa: E402
from tests.support import override_get_db, test_engine  # noqa: E402

app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
async def setup_db():
    """Set up test database."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client():
    """Create test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def auth_enabled():
    """Turn authentication on for one test, then put it back.

    The middleware holds the same Settings instance the app was built with, and
    get_settings() is cached, so mutating that object switches auth on without
    rebuilding the app.
    """
    from src.auth.security import generate_secret_key, hash_password
    from src.config import get_settings

    settings = get_settings()
    before = (settings.auth_password_hash, settings.secret_key, settings.api_key)

    settings.auth_password_hash = hash_password("correct horse")
    settings.secret_key = generate_secret_key()
    settings.api_key = "test-api-key"
    try:
        yield settings
    finally:
        settings.auth_password_hash, settings.secret_key, settings.api_key = before
