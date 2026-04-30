from datetime import UTC, datetime
from typing import Annotated, NamedTuple

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.models import APIKey, Tenant, TenantUser, User
from app.services.security import decode_access_token, hash_api_key

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class AuthenticatedUser(NamedTuple):
    user: User
    tenant: Tenant
    role: str


class AuthenticatedAPIKey(NamedTuple):
    api_key: APIKey
    tenant: Tenant


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


async def get_api_key_context(
    raw_api_key: Annotated[str | None, Depends(api_key_header)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthenticatedAPIKey:
    if raw_api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
        )

    result = await db_session.execute(
        select(APIKey, Tenant)
        .join(Tenant, Tenant.id == APIKey.tenant_id)
        .where(APIKey.key_hash == hash_api_key(raw_api_key))
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    api_key, tenant = row
    if not tenant.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive tenant",
        )
    if not api_key.is_active or api_key.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive API key",
        )
    if api_key.expires_at is not None and api_key.expires_at <= datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Expired API key",
        )

    api_key.last_used_at = datetime.now(UTC)
    await db_session.flush()
    return AuthenticatedAPIKey(api_key=api_key, tenant=tenant)
