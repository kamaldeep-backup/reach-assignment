import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tenant, TenantRuntimeQuota, TenantUser, User


async def create_user_with_tenant(
    *,
    db_session: AsyncSession,
    email: str,
    password_hash: str,
    tenant_name: str,
) -> tuple[User, Tenant, TenantUser]:
    tenant = Tenant(name=tenant_name)
    user = User(email=email, password_hash=password_hash)
    db_session.add_all([tenant, user])
    await db_session.flush()

    membership = TenantUser(tenant_id=tenant.id, user_id=user.id, role="owner")
    runtime_quota = TenantRuntimeQuota(tenant_id=tenant.id)
    db_session.add_all([membership, runtime_quota])
    await db_session.flush()
    return user, tenant, membership


async def get_user_by_email(
    *,
    db_session: AsyncSession,
    email: str,
) -> User | None:
    result = await db_session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_with_primary_tenant(
    *,
    db_session: AsyncSession,
    user_id: uuid.UUID,
) -> tuple[User, Tenant, str] | None:
    result = await db_session.execute(
        select(User, Tenant, TenantUser.role)
        .join(TenantUser, TenantUser.user_id == User.id)
        .join(Tenant, Tenant.id == TenantUser.tenant_id)
        .where(User.id == user_id)
        .order_by(TenantUser.created_at.asc())
    )
    row = result.first()
    if row is None:
        return None
    user, tenant, role = row
    return user, tenant, role


async def update_last_login_at(
    *,
    db_session: AsyncSession,
    user: User,
    last_login_at: datetime,
) -> None:
    user.last_login_at = last_login_at
    await db_session.flush()
