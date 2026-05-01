"""add worker queue database layer

Revision ID: 20260501_0004
Revises: 20260430_0003
Create Date: 2026-05-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260501_0004"
down_revision: Union[str, Sequence[str], None] = "20260430_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE job_status ADD VALUE IF NOT EXISTS 'DEAD_LETTERED'")

    op.add_column(
        "tenants",
        sa.Column("max_running_jobs", sa.Integer(), server_default="5", nullable=False),
    )
    op.add_column(
        "tenants",
        sa.Column("submit_rate_limit", sa.Integer(), server_default="60", nullable=False),
    )
    op.create_check_constraint(
        "ck_tenants_max_running_jobs",
        "tenants",
        "max_running_jobs > 0",
    )
    op.create_check_constraint(
        "ck_tenants_submit_rate_limit",
        "tenants",
        "submit_rate_limit > 0",
    )

    op.add_column(
        "jobs",
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "jobs",
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
    )
    op.add_column(
        "jobs",
        sa.Column(
            "run_after",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "jobs",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("jobs", sa.Column("locked_by", sa.Text(), nullable=True))
    op.create_check_constraint("ck_jobs_attempts_non_negative", "jobs", "attempts >= 0")
    op.create_check_constraint(
        "ck_jobs_max_attempts_positive",
        "jobs",
        "max_attempts > 0",
    )
    op.create_index(
        "idx_jobs_claim",
        "jobs",
        ["status", "run_after", sa.text("priority DESC"), "created_at"],
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.create_index(
        "idx_jobs_running_lease",
        "jobs",
        ["status", "lease_expires_at"],
        postgresql_where=sa.text("status = 'RUNNING'"),
    )

    op.create_table(
        "tenant_runtime_quotas",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("running_jobs", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "running_jobs >= 0",
            name="ck_tenant_runtime_quotas_running_jobs",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tenant_id"),
    )
    op.execute(
        """
        INSERT INTO tenant_runtime_quotas (tenant_id)
        SELECT id
        FROM tenants
        ON CONFLICT (tenant_id) DO NOTHING
        """
    )

    op.create_table(
        "dead_letter_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("final_error", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column(
            "dead_lettered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attempts > 0",
            name="ck_dead_letter_jobs_attempts_positive",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_dead_letter_jobs_job_id"),
    )
    op.create_index(
        "idx_dead_letter_jobs_tenant",
        "dead_letter_jobs",
        ["tenant_id", "dead_lettered_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_dead_letter_jobs_tenant", table_name="dead_letter_jobs")
    op.drop_table("dead_letter_jobs")

    op.drop_table("tenant_runtime_quotas")

    op.drop_index("idx_jobs_running_lease", table_name="jobs")
    op.drop_index("idx_jobs_claim", table_name="jobs")
    op.drop_constraint("ck_jobs_max_attempts_positive", "jobs", type_="check")
    op.drop_constraint("ck_jobs_attempts_non_negative", "jobs", type_="check")
    op.drop_column("jobs", "locked_by")
    op.drop_column("jobs", "lease_expires_at")
    op.drop_column("jobs", "run_after")
    op.drop_column("jobs", "max_attempts")
    op.drop_column("jobs", "attempts")

    op.drop_constraint("ck_tenants_submit_rate_limit", "tenants", type_="check")
    op.drop_constraint("ck_tenants_max_running_jobs", "tenants", type_="check")
    op.drop_column("tenants", "submit_rate_limit")
    op.drop_column("tenants", "max_running_jobs")

    op.execute("UPDATE jobs SET status = 'FAILED' WHERE status = 'DEAD_LETTERED'")
    op.execute(
        "UPDATE job_events SET from_status = 'FAILED' "
        "WHERE from_status = 'DEAD_LETTERED'"
    )
    op.execute(
        "UPDATE job_events SET to_status = 'FAILED' "
        "WHERE to_status = 'DEAD_LETTERED'"
    )
    op.execute("ALTER TABLE jobs ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TYPE job_status RENAME TO job_status_with_dead_lettered")
    old_job_status = postgresql.ENUM(
        "PENDING",
        "RUNNING",
        "SUCCEEDED",
        "FAILED",
        "CANCELLED",
        name="job_status",
    )
    old_job_status.create(op.get_bind(), checkfirst=False)
    op.execute(
        "ALTER TABLE jobs ALTER COLUMN status TYPE job_status "
        "USING status::text::job_status"
    )
    op.execute(
        "ALTER TABLE job_events ALTER COLUMN from_status TYPE job_status "
        "USING from_status::text::job_status"
    )
    op.execute(
        "ALTER TABLE job_events ALTER COLUMN to_status TYPE job_status "
        "USING to_status::text::job_status"
    )
    op.execute("ALTER TABLE jobs ALTER COLUMN status SET DEFAULT 'PENDING'")
    op.execute("DROP TYPE job_status_with_dead_lettered")
