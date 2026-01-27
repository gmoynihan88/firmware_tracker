"""Initial migration

Revision ID: 001
Revises:
Create Date: 2024-01-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create manufacturers table
    op.create_table(
        "manufacturers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("website_url", sa.String(500), nullable=True),
        sa.Column("scraper_type", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_manufacturers_id", "manufacturers", ["id"])

    # Create device_models table
    op.create_table(
        "device_models",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("manufacturer_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "category",
            sa.Enum(
                "guitar_pedal",
                "audio_interface",
                "synthesizer",
                "midi_controller",
                "vst_plugin",
                "other",
                name="devicecategory",
            ),
            nullable=True,
        ),
        sa.Column("firmware_page_url", sa.String(500), nullable=True),
        sa.Column("product_url", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["manufacturer_id"], ["manufacturers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_device_models_id", "device_models", ["id"])

    # Create firmware_versions table
    op.create_table(
        "firmware_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_model_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("release_date", sa.DateTime(), nullable=True),
        sa.Column("download_url", sa.String(500), nullable=True),
        sa.Column("changelog_raw", sa.Text(), nullable=True),
        sa.Column("changelog_summary", sa.Text(), nullable=True),
        sa.Column("is_latest", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["device_model_id"], ["device_models.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_firmware_versions_id", "firmware_versions", ["id"])

    # Create my_devices table
    op.create_table(
        "my_devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_model_id", sa.Integer(), nullable=False),
        sa.Column("nickname", sa.String(255), nullable=True),
        sa.Column("serial_number", sa.String(255), nullable=True),
        sa.Column("current_firmware_version", sa.String(50), nullable=True),
        sa.Column("notify_on_update", sa.Boolean(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["device_model_id"], ["device_models.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_my_devices_id", "my_devices", ["id"])

    # Create notifications table
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("my_device_id", sa.Integer(), nullable=False),
        sa.Column("firmware_version_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("read", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["firmware_version_id"], ["firmware_versions.id"]),
        sa.ForeignKeyConstraint(["my_device_id"], ["my_devices.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notifications_id", "notifications", ["id"])


def downgrade() -> None:
    op.drop_index("ix_notifications_id", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_my_devices_id", table_name="my_devices")
    op.drop_table("my_devices")
    op.drop_index("ix_firmware_versions_id", table_name="firmware_versions")
    op.drop_table("firmware_versions")
    op.drop_index("ix_device_models_id", table_name="device_models")
    op.drop_table("device_models")
    op.drop_index("ix_manufacturers_id", table_name="manufacturers")
    op.drop_table("manufacturers")
