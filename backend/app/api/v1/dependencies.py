from typing import Annotated, NamedTuple

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.models import Tenant, TenantUser, User
from app.services.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


class AuthenticatedUser(NamedTuple):
    user: User
    tenant: Tenant
    role: str


async def get_current_user_context(
    token: Annotated[str, Depends(oauth2_scheme)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthenticatedUser:
    user_id = decode_access_token(token)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db_session.execute(
        select(User, Tenant, TenantUser.role)
        .join(TenantUser, TenantUser.user_id == User.id)
        .join(Tenant, Tenant.id == TenantUser.tenant_id)
        .where(User.id == user_id)
        .order_by(TenantUser.created_at.asc())
    )
    row = result.first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user, tenant, role = row
    if not user.is_active or not tenant.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user or tenant",
        )
    return AuthenticatedUser(user=user, tenant=tenant, role=role)
