from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.config import get_settings
from src.database import init_db
from src.devices.router import router as devices_router
from src.firmware.router import router as firmware_router
from src.web.router import router as web_router
from src.scheduler.scheduler import start_scheduler, shutdown_scheduler

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    await init_db()
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
app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")

# Include API routers
app.include_router(devices_router, prefix="/api", tags=["devices"])
app.include_router(firmware_router, prefix="/api/firmware", tags=["firmware"])

# Include web router (HTML pages)
app.include_router(web_router, tags=["web"])
