"""Login and logout."""
import logging

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.auth.middleware import SESSION_COOKIE
from src.auth.security import issue_token, verify_password
from src.auth.throttle import client_address, get_login_throttle
from src.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
# Shared environment, so asset_version() is available to every template.
from src.templating import templates  # noqa: E402

router = APIRouter(tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    current = get_settings()
    if not (current.auth_password_hash and current.secret_key):
        # Nothing to log into; sending someone to a form that cannot succeed is worse
        # than telling them auth is off.
        return RedirectResponse(url="/", status_code=303)

    # public_catalog decides whether the page can offer the catalogue as somewhere to go
    # instead. Offering it when the catalogue is private would send someone straight back
    # here, which is worse than not offering it at all.
    return templates.TemplateResponse(
        request,
        name="login.html",
        context={
            "error": None,
            "unread_count": 0,
            "public_catalog": current.public_catalog,
        },
    )


@router.post("/login", response_class=HTMLResponse)
async def login(request: Request, password: str = Form(...)):
    current = get_settings()
    if not (current.auth_password_hash and current.secret_key):
        return RedirectResponse(url="/", status_code=303)

    throttle = get_login_throttle(current)
    client = client_address(request)

    wait = throttle.retry_after(client)
    if wait is not None:
        # The limit counts failures, so this is only ever reached after several wrong
        # passwords from this address. Retry-After says when it clears.
        logger.warning("Login attempts from %s throttled for %ss", client, wait)
        return templates.TemplateResponse(
            request,
            name="login.html",
            context={
                "error": "Too many attempts. Try again shortly.",
                "unread_count": 0,
                "public_catalog": current.public_catalog,
            },
            status_code=429,
            headers={"Retry-After": str(wait)},
        )

    if not verify_password(password, current.auth_password_hash):
        throttle.record_failure(client)
        # Deliberately vague, and logged without the attempted password.
        logger.warning("Failed login attempt from %s", client)
        return templates.TemplateResponse(
            request,
            name="login.html",
            context={
                "error": "Incorrect password.",
                "unread_count": 0,
                "public_catalog": current.public_catalog,
            },
            status_code=401,
        )

    throttle.clear(client)
    token = issue_token(current.secret_key, current.session_lifetime_hours * 3600)
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=current.session_lifetime_hours * 3600,
        httponly=True,      # not readable from JavaScript
        samesite="lax",     # survives a normal navigation, not a cross-site POST
        # TLS ends at CloudFront, so the request the app sees is http and the scheme
        # alone would drop the flag on exactly the deployment that needs it.
        secure=current.session_cookie_secure or request.url.scheme == "https",
    )
    return response


@router.get("/logout")
async def logout(request: Request):
    current = get_settings()
    response = RedirectResponse(url="/login", status_code=303)
    # A cookie is only replaced by one with the same attributes, so clearing has to
    # match how it was set.
    response.delete_cookie(
        SESSION_COOKIE,
        httponly=True,
        samesite="lax",
        secure=current.session_cookie_secure or request.url.scheme == "https",
    )
    return response
