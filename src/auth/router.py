"""Login and logout."""
import logging

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.auth.middleware import SESSION_COOKIE
from src.auth.security import issue_token, verify_password
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

    return templates.TemplateResponse(
        request, name="login.html", context={"error": None, "unread_count": 0}
    )


@router.post("/login", response_class=HTMLResponse)
async def login(request: Request, password: str = Form(...)):
    current = get_settings()
    if not (current.auth_password_hash and current.secret_key):
        return RedirectResponse(url="/", status_code=303)

    if not verify_password(password, current.auth_password_hash):
        # Deliberately vague, and logged without the attempted password.
        logger.warning("Failed login attempt from %s", request.client.host if request.client else "unknown")
        return templates.TemplateResponse(
            request,
            name="login.html",
            context={"error": "Incorrect password.", "unread_count": 0},
            status_code=401,
        )

    token = issue_token(current.secret_key, current.session_lifetime_hours * 3600)
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=current.session_lifetime_hours * 3600,
        httponly=True,      # not readable from JavaScript
        samesite="lax",     # survives a normal navigation, not a cross-site POST
        secure=request.url.scheme == "https",
    )
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response
