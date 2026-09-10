from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database import Base
from src.devices.models import (
    Manufacturer,
    DeviceModel,
    FirmwareVersion,
    MyDevice,
    Notification,
)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# alembic.ini carries a sync sqlite:/// URL while the app uses an async one, so the
# two can disagree about which file they mean. In a container they always do: the
# database lives on a mounted volume, and a migration run against alembic.ini's
# relative path would quietly create and migrate a second, empty database inside the
# image. Prefer DATABASE_URL when it is set, converted to the sync driver.
_database_url = os.getenv("DATABASE_URL")
if _database_url:
    config.set_main_option(
        "sqlalchemy.url", _database_url.replace("sqlite+aiosqlite://", "sqlite://")
    )

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
