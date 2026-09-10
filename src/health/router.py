"""Health endpoints for container orchestration.

Two checks, because they answer different questions and a load balancer needs both:

- /health is liveness. It touches nothing and always answers, so a failure means the
  process is wedged or gone. Making it depend on the database would have a slow disk
  cause tasks to be killed and replaced, which does not fix a slow disk.
- /health/ready is readiness. It runs a trivial query, so a failure means this task
  cannot serve requests -- on the planned deployment the database is a file on EFS,
  and losing that mount is exactly the case worth catching.

Neither requires authentication, and neither should: a load balancer cannot present
credentials, and an unauthenticated 200 here discloses nothing.
"""
import logging
import time

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

# Set once at import, so uptime measures this process rather than the request.
_STARTED_AT = time.monotonic()


@router.get("/health")
async def health() -> dict:
    """Liveness: the process is running and can answer a request."""
    return {"status": "ok", "uptime_seconds": round(time.monotonic() - _STARTED_AT, 1)}


@router.get("/health/ready")
async def ready(response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    """Readiness: the database answers, so this task can serve real traffic.

    Returns 503 rather than raising, so the body still explains what failed -- a
    health check that returns an empty error is one you end up debugging by hand.
    """
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        # Logged at warning, not error: a readiness probe failing is expected during
        # startup and rollout, and should not page anyone on its own.
        logger.warning("Readiness check failed: %s", exc)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable", "database": "unreachable", "detail": str(exc)[:200]}

    return {"status": "ok", "database": "ok"}
