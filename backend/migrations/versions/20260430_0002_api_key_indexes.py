"""add api key lookup indexes

Revision ID: 20260430_0002
Revises: 20260430_0001
Create Date: 2026-04-30
"""
from typing import Sequence, Union

from alembic import op

revision: str = "20260430_0002"
down_revision: Union[str, Sequence[str], None] = "20260430_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_api_keys_tenant_created",
        "api_keys",
        ["tenant_id", "created_at"],
    )
    op.create_index("idx_api_keys_key_prefix", "api_keys", ["key_prefix"])


def downgrade() -> None:
    op.drop_index("idx_api_keys_key_prefix", table_name="api_keys")
    op.drop_index("idx_api_keys_tenant_created", table_name="api_keys")
