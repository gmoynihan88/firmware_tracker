import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from src.config import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_async_engine(settings.database_url, echo=settings.debug)
async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


def _check_db_integrity(conn) -> bool:
    """Check if expected tables exist. Returns False if alembic stamp is present but tables are missing."""
    result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
    tables = {row[0] for row in result.fetchall()}
    has_alembic = "alembic_version" in tables
    has_app_tables = "manufacturers" in tables and "device_models" in tables
    return not has_alembic or has_app_tables


def _clear_alembic_stamp(conn):
    conn.execute(text("DELETE FROM alembic_version"))


async def init_db():
    async with engine.begin() as conn:
        healthy = await conn.run_sync(_check_db_integrity)

    if not healthy:
        import subprocess, sys
        logger.warning("Database tables missing but alembic stamp present; repairing")
        async with engine.begin() as conn:
            await conn.run_sync(_clear_alembic_stamp)
        await engine.dispose()
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            check=True,
        )
        logger.info("Database repaired successfully")
    else:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
