import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import AuthenticatedUser, get_current_user_context
from app.core.database import get_db_session
from app.models import APIKey
from app.observability.tracing import log_event, trace_span
from app.repositories import api_keys as api_keys_repository
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
    with trace_span("api_keys.create", tenantId=current_user.tenant.id):
        api_key = await api_keys_repository.create_api_key(
            db_session=db_session,
            tenant_id=current_user.tenant.id,
            created_by_user_id=current_user.user.id,
            key_hash=hash_api_key(raw_api_key),
            key_prefix=key_prefix,
            name=request.name,
            scopes=request.scopes,
            expires_at=request.expires_at,
        )

    log_event(
        "api_keys.created",
        tenantId=current_user.tenant.id,
        apiKeyId=api_key.id,
        keyPrefix=api_key.key_prefix,
    )
    return APIKeyCreateResponse(
        **serialize_api_key(api_key).model_dump(by_alias=True),
        apiKey=raw_api_key,
    )


@router.get("", response_model=list[APIKeyResponse])
async def list_api_keys(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user_context)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[APIKeyResponse]:
    api_keys = await api_keys_repository.list_tenant_api_keys(
        db_session=db_session,
        tenant_id=current_user.tenant.id,
    )
    return [serialize_api_key(api_key) for api_key in api_keys]


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
        with trace_span(
            "api_keys.revoke",
            tenantId=current_user.tenant.id,
            apiKeyId=api_key.id,
        ):
            await api_keys_repository.revoke_api_key(
                db_session=db_session,
                api_key=api_key,
                revoked_at=datetime.now(UTC),
            )
        log_event(
            "api_keys.revoked",
            tenantId=current_user.tenant.id,
            apiKeyId=api_key.id,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def get_tenant_api_key_or_404(
    api_key_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db_session: AsyncSession,
) -> APIKey:
    api_key = await api_keys_repository.get_tenant_api_key(
        db_session=db_session,
        tenant_id=tenant_id,
        api_key_id=api_key_id,
    )
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found",
        )
    return api_key
