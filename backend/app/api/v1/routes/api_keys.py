import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import AuthenticatedUser, get_current_user_context
from app.core.database import get_db_session
from app.models import APIKey
from app.schemas import APIKeyCreateRequest, APIKeyCreateResponse, APIKeyResponse
from app.services.security import generate_api_key, hash_api_key

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


def serialize_api_key(api_key: APIKey) -> APIKeyResponse:
    return APIKeyResponse(
        apiKeyId=api_key.id,
        name=api_key.name,
        keyPrefix=api_key.key_prefix,
        scopes=api_key.scopes,
        isActive=api_key.is_active,
        expiresAt=api_key.expires_at,
        lastUsedAt=api_key.last_used_at,
        createdAt=api_key.created_at,
        revokedAt=api_key.revoked_at,
    )


@router.post(
    "",
    response_model=APIKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_key(
    request: APIKeyCreateRequest,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user_context)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIKeyCreateResponse:
    raw_api_key, key_prefix = generate_api_key()
    api_key = APIKey(
        tenant_id=current_user.tenant.id,
        created_by_user_id=current_user.user.id,
        key_hash=hash_api_key(raw_api_key),
        key_prefix=key_prefix,
        name=request.name,
        scopes=request.scopes,
        expires_at=request.expires_at,
    )
    db_session.add(api_key)
    await db_session.flush()
    await db_session.refresh(api_key)

    return APIKeyCreateResponse(
        **serialize_api_key(api_key).model_dump(by_alias=True),
        apiKey=raw_api_key,
    )


@router.get("", response_model=list[APIKeyResponse])
async def list_api_keys(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user_context)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[APIKeyResponse]:
    result = await db_session.execute(
        select(APIKey)
        .where(APIKey.tenant_id == current_user.tenant.id)
        .order_by(APIKey.created_at.desc(), APIKey.id.desc())
    )
    return [serialize_api_key(api_key) for api_key in result.scalars().all()]


@router.get("/{api_key_id}", response_model=APIKeyResponse)
async def get_api_key(
    api_key_id: uuid.UUID,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user_context)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIKeyResponse:
    api_key = await get_tenant_api_key_or_404(
        api_key_id=api_key_id,
        tenant_id=current_user.tenant.id,
        db_session=db_session,
    )
    return serialize_api_key(api_key)


@router.delete("/{api_key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    api_key_id: uuid.UUID,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user_context)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    api_key = await get_tenant_api_key_or_404(
        api_key_id=api_key_id,
        tenant_id=current_user.tenant.id,
        db_session=db_session,
    )
    if api_key.revoked_at is None:
        api_key.is_active = False
        api_key.revoked_at = datetime.now(UTC)
        await db_session.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def get_tenant_api_key_or_404(
    api_key_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db_session: AsyncSession,
) -> APIKey:
    result = await db_session.execute(
        select(APIKey).where(APIKey.id == api_key_id, APIKey.tenant_id == tenant_id)
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found",
        )
    return api_key
