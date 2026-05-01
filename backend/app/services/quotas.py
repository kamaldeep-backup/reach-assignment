import uuid

from sqlalchemy import text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TenantRuntimeQuota


async def ensure_runtime_quota(
    *,
    db_session: AsyncSession,
    tenant_id: uuid.UUID,
) -> None:
    await db_session.execute(
        insert(TenantRuntimeQuota)
        .values(tenant_id=tenant_id)
        .on_conflict_do_nothing(index_elements=[TenantRuntimeQuota.tenant_id])
    )


async def reserve_runtime_slot(
    *,
    db_session: AsyncSession,
    tenant_id: uuid.UUID,
) -> bool:
    await ensure_runtime_quota(db_session=db_session, tenant_id=tenant_id)
    result = await db_session.execute(
        text(
            """
            UPDATE tenant_runtime_quotas AS q
            SET running_jobs = q.running_jobs + 1,
                updated_at = now()
            FROM tenants AS t
            WHERE q.tenant_id = t.id
              AND q.tenant_id = :tenant_id
              AND q.running_jobs < t.max_running_jobs
            """
        ),
        {"tenant_id": tenant_id},
    )
    return result.rowcount == 1


async def release_runtime_slot(
    *,
    db_session: AsyncSession,
    tenant_id: uuid.UUID,
) -> None:
    await ensure_runtime_quota(db_session=db_session, tenant_id=tenant_id)
    await db_session.execute(
        update(TenantRuntimeQuota)
        .where(TenantRuntimeQuota.tenant_id == tenant_id)
        .where(TenantRuntimeQuota.running_jobs > 0)
        .values(running_jobs=TenantRuntimeQuota.running_jobs - 1)
    )
