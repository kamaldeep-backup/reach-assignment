import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import APIKey, Tenant


async def create_api_key(
    *,
    db_session: AsyncSession,
    tenant_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
    key_hash: str,
    key_prefix: str,
    name: str,
    scopes: list[str],
    expires_at: datetime | None,
) -> APIKey:
    api_key = APIKey(
        tenant_id=tenant_id,
        created_by_user_id=created_by_user_id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=name,
        scopes=scopes,
        expires_at=expires_at,
    )
    db_session.add(api_key)
    await db_session.flush()
    await db_session.refresh(api_key)
    return api_key


async def list_tenant_api_keys(
    *,
    db_session: AsyncSession,
    tenant_id: uuid.UUID,
) -> list[APIKey]:
    result = await db_session.execute(
        select(APIKey)
        .where(APIKey.tenant_id == tenant_id)
        .order_by(APIKey.created_at.desc(), APIKey.id.desc())
    )
    return list(result.scalars().all())


async def get_tenant_api_key(
    *,
    db_session: AsyncSession,
    tenant_id: uuid.UUID,
    api_key_id: uuid.UUID,
) -> APIKey | None:
    result = await db_session.execute(
        select(APIKey).where(APIKey.id == api_key_id, APIKey.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


async def get_api_key_with_tenant_by_hash(
    *,
    db_session: AsyncSession,
    key_hash: str,
) -> tuple[APIKey, Tenant] | None:
    result = await db_session.execute(
        select(APIKey, Tenant)
        .join(Tenant, Tenant.id == APIKey.tenant_id)
        .where(APIKey.key_hash == key_hash)
    )
    row = result.one_or_none()
    if row is None:
        return None
    api_key, tenant = row
    return api_key, tenant


async def revoke_api_key(
    *,
    db_session: AsyncSession,
    api_key: APIKey,
    revoked_at: datetime,
) -> None:
    api_key.is_active = False
    api_key.revoked_at = revoked_at
    await db_session.flush()


async def update_last_used_at(
    *,
    db_session: AsyncSession,
    api_key: APIKey,
    last_used_at: datetime,
) -> None:
    api_key.last_used_at = last_used_at
    await db_session.flush()
