"""add unique job lease token

Revision ID: 20260503_0007
Revises: 20260503_0006
Create Date: 2026-05-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260503_0007"
down_revision: Union[str, Sequence[str], None] = "20260503_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("lease_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "uq_jobs_lease_id",
        "jobs",
        ["lease_id"],
        unique=True,
        postgresql_where=sa.text("lease_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_jobs_lease_id", table_name="jobs")
    op.drop_column("jobs", "lease_id")
