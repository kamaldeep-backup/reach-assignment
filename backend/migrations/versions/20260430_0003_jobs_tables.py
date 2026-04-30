"""create jobs tables

Revision ID: 20260430_0003
Revises: 20260430_0002
Create Date: 2026-04-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260430_0003"
down_revision: Union[str, Sequence[str], None] = "20260430_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

job_status = postgresql.ENUM(
    "PENDING",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
    "CANCELLED",
    name="job_status",
)
job_status_column = postgresql.ENUM(
    "PENDING",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
    "CANCELLED",
    name="job_status",
    create_type=False,
)


def upgrade() -> None:
    job_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            job_status_column,
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_jobs_tenant_idempotency",
        ),
    )
    op.create_index(
        "idx_jobs_tenant_status",
        "jobs",
        ["tenant_id", "status", "created_at"],
    )
    op.create_index(
        "idx_jobs_tenant_created",
        "jobs",
        ["tenant_id", "created_at"],
    )
    op.create_table(
        "job_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("from_status", job_status_column, nullable=True),
        sa.Column("to_status", job_status_column, nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_job_events_job_id",
        "job_events",
        ["job_id", "created_at"],
    )
    op.create_index(
        "idx_job_events_tenant_created",
        "job_events",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_job_events_tenant_created", table_name="job_events")
    op.drop_index("idx_job_events_job_id", table_name="job_events")
    op.drop_table("job_events")
    op.drop_index("idx_jobs_tenant_created", table_name="jobs")
    op.drop_index("idx_jobs_tenant_status", table_name="jobs")
    op.drop_table("jobs")
    job_status.drop(op.get_bind(), checkfirst=True)
