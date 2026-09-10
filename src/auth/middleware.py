"""Request authentication.

Off unless AUTH_PASSWORD_HASH is set, so an existing local install keeps working
with no configuration. That default is only safe because the app is meant to run on
localhost until deployed; startup logs a warning naming what is exposed, and the
README says to configure it before putting the app on a public address.
"""
import hmac
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from src.auth.security import read_token
from src.config import Settings, get_settings

logger = logging.getLogger(__name__)

SESSION_COOKIE = "firmware_tracker_session"

# Reachable without credentials. Health checks are here because a load balancer
# cannot present any, and the login page and its static assets because requiring
# auth to reach the login form is a redirect loop.
PUBLIC_PATHS = ("/health", "/health/ready", "/login", "/logout")
PUBLIC_PREFIXES = ("/static/",)


def is_public(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)


def wants_html(request: Request) -> bool:
    """Whether to redirect to the login page or answer 401.

    A browser navigating should land on the form; curl and the scheduler should get
    a status code they can act on rather than a page of HTML.
    """
    return "text/html" in request.headers.get("accept", "")


def auth_is_enabled(settings: Settings) -> bool:
    """Both halves are required.

    A password hash with no secret key cannot sign a session, so treating that as
    "enabled" would lock everyone out of an app that still serves every endpoint.
    """
    return bool(settings.auth_password_hash and settings.secret_key)


def is_authenticated(request: Request, settings: Settings) -> bool:
    if read_token(request.cookies.get(SESSION_COOKIE, ""), settings.secret_key):
        return True

    # An API key is an alternative for programmatic callers, never a fallback for a
    # failed session: it is only accepted when one is actually configured, so an
    # unset key does not mean every key works.
    if settings.api_key:
        presented = request.headers.get("x-api-key", "")
        if presented and hmac.compare_digest(presented, settings.api_key):
            return True

    return False


class AuthMiddleware(BaseHTTPMiddleware):
    """Resolves settings per request rather than capturing them at construction.

    The app is built once at import; reading the current settings on each request
    keeps the middleware honest if that object is ever replaced or amended.
    """

    async def dispatch(self, request: Request, call_next):
        settings = get_settings()

        if not auth_is_enabled(settings) or is_public(request.url.path):
            return await call_next(request)

        if is_authenticated(request, settings):
            return await call_next(request)

        if wants_html(request):
            return RedirectResponse(url="/login", status_code=303)

        return JSONResponse(
            {"detail": "Not authenticated"},
            status_code=401,
            headers={"WWW-Authenticate": "Cookie"},
        )


def warn_if_unprotected(settings: Settings) -> None:
    """Say plainly what is exposed when auth is not configured."""
    if settings.auth_password_hash and settings.secret_key:
        return

    if settings.auth_password_hash and not settings.secret_key:
        logger.warning(
            "AUTH_PASSWORD_HASH is set but SECRET_KEY is not, so authentication is "
            "DISABLED. Generate one with: python -m src.auth.hash_password"
        )
        return

    logger.warning(
        "Authentication is disabled: every endpoint is open, including "
        "POST /api/firmware/scrape-all and full CRUD on your devices. Fine on "
        "localhost; configure AUTH_PASSWORD_HASH and SECRET_KEY before exposing this."
    )
