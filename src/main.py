from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.config import get_settings
from src.database import init_db
from src.logging_config import configure_logging
from src.devices.router import router as devices_router
from src.firmware.router import router as firmware_router
from src.auth.middleware import AuthMiddleware, warn_if_unprotected
from src.auth.router import router as auth_router
from src.health.router import router as health_router
from src.web.router import router as web_router
from src.scheduler.scheduler import start_scheduler, shutdown_scheduler

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup. Logging goes first so everything below it is actually visible.
    configure_logging(settings)
    await init_db()
    warn_if_unprotected(settings)
    start_scheduler()
    yield
    # Shutdown
    shutdown_scheduler()


app = FastAPI(
    title=settings.app_name,
    description="Track firmware updates for music devices",
    version="0.1.0",
    lifespan=lifespan,
)

# Mount static files
class VersionedStaticFiles(StaticFiles):
    """Static assets, cached hard because their URLs carry a content hash.

    Without an explicit Cache-Control a browser falls back to heuristic caching: with
    only Last-Modified to go on it may reuse a stale file without revalidating, which
    is why a changed stylesheet could appear not to have changed. Caching for a year
    is safe precisely because the URL changes whenever the file does.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


app.mount("/static", VersionedStaticFiles(directory=str(settings.static_dir)), name="static")

# Include API routers
# Authentication wraps everything except the paths listed in the middleware:
# health checks, the login page and static assets.
app.add_middleware(AuthMiddleware)

app.include_router(auth_router)

# Health endpoints are deliberately unprefixed and unauthenticated: a load
# balancer cannot present credentials and does not know about /api.
app.include_router(health_router)

app.include_router(devices_router, prefix="/api", tags=["devices"])
app.include_router(firmware_router, prefix="/api/firmware", tags=["firmware"])

# Include web router (HTML pages)
app.include_router(web_router, tags=["web"])
