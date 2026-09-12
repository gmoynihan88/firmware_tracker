"""Add last_seen_at to firmware_versions

A version the vendor has withdrawn simply stops being returned by the scrape, and
without this its row looks identical to one confirmed this morning. The gap between
last_seen_at and now is also what separates "still current" from "we stopped
looking".

Existing rows are backfilled from created_at rather than from now. Stamping them all
with the deployment time would assert that every version was confirmed present on a
day nothing was checked, which is the kind of invented precision this project keeps
finding in vendors' pages.

Revision ID: a4f1c2d7e8b9
Revises: 81b8abce3858
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a4f1c2d7e8b9'
down_revision: Union[str, None] = '81b8abce3858'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "firmware_versions", sa.Column("last_seen_at", sa.DateTime(), nullable=True)
    )
    op.execute("UPDATE firmware_versions SET last_seen_at = created_at")
    op.create_index(
        op.f("ix_firmware_versions_last_seen_at"), "firmware_versions", ["last_seen_at"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_firmware_versions_last_seen_at"), table_name="firmware_versions")
    op.drop_column("firmware_versions", "last_seen_at")
