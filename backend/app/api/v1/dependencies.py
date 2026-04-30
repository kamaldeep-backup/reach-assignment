from datetime import UTC, datetime
from typing import Annotated, NamedTuple

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.models import APIKey, Tenant, User
from app.repositories import api_keys as api_keys_repository
from app.repositories import users as users_repository
from app.services.security import decode_access_token, hash_api_key

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
optional_oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    auto_error=False,
)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class AuthenticatedUser(NamedTuple):
    user: User
    tenant: Tenant
    role: str


class AuthenticatedAPIKey(NamedTuple):
    api_key: APIKey
    tenant: Tenant


class AuthenticatedTenant(NamedTuple):
    tenant: Tenant
    user: User | None
    api_key: APIKey | None
    role: str | None


async def get_current_user_context(
    token: Annotated[str, Depends(oauth2_scheme)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthenticatedUser:
    return await resolve_user_context(token=token, db_session=db_session)


async def resolve_user_context(
    token: str,
    db_session: AsyncSession,
) -> AuthenticatedUser:
    user_id = decode_access_token(token)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    row = await users_repository.get_user_with_primary_tenant(
        db_session=db_session,
        user_id=user_id,
    )
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
    return await resolve_api_key_context(raw_api_key=raw_api_key, db_session=db_session)


async def resolve_api_key_context(
    raw_api_key: str,
    db_session: AsyncSession,
) -> AuthenticatedAPIKey:
    row = await api_keys_repository.get_api_key_with_tenant_by_hash(
        db_session=db_session,
        key_hash=hash_api_key(raw_api_key),
    )
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

    await api_keys_repository.update_last_used_at(
        db_session=db_session,
        api_key=api_key,
        last_used_at=datetime.now(UTC),
    )
    return AuthenticatedAPIKey(api_key=api_key, tenant=tenant)


async def get_current_tenant_context(
    token: Annotated[str | None, Depends(optional_oauth2_scheme)],
    raw_api_key: Annotated[str | None, Depends(api_key_header)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthenticatedTenant:
    if token is not None:
        user_context = await resolve_user_context(token=token, db_session=db_session)
        return AuthenticatedTenant(
            tenant=user_context.tenant,
            user=user_context.user,
            api_key=None,
            role=user_context.role,
        )
    if raw_api_key is not None:
        api_key_context = await resolve_api_key_context(
            raw_api_key=raw_api_key,
            db_session=db_session,
        )
        return AuthenticatedTenant(
            tenant=api_key_context.tenant,
            user=None,
            api_key=api_key_context.api_key,
            role=None,
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_api_key_scope(context: AuthenticatedTenant, scope: str) -> None:
    if context.api_key is not None and scope not in context.api_key.scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"API key is missing required scope: {scope}",
        )
