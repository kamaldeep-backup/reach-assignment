"""include event id in job event stream cursor index

Revision ID: 20260503_0006
Revises: 20260502_0005
Create Date: 2026-05-03
"""
from typing import Sequence, Union

from alembic import op

revision: str = "20260503_0006"
down_revision: Union[str, Sequence[str], None] = "20260502_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("idx_job_events_tenant_created", table_name="job_events")
    op.create_index(
        "idx_job_events_tenant_created",
        "job_events",
        ["tenant_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("idx_job_events_tenant_created", table_name="job_events")
    op.create_index(
        "idx_job_events_tenant_created",
        "job_events",
        ["tenant_id", "created_at"],
    )
