from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import AuthenticatedUser, get_current_user_context
from app.core.database import get_db_session
from app.models import Tenant, TenantUser, User
from app.schemas import CurrentUserResponse, RegisterRequest, RegisterResponse, TokenResponse
from app.services.security import (
    create_access_token,
    hash_password,
    normalize_email,
    verify_password_with_dummy,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    request: RegisterRequest,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RegisterResponse:
    email = normalize_email(request.email)
    tenant = Tenant(name=request.tenant_name)
    user = User(email=email, password_hash=hash_password(request.password))
    db_session.add_all([tenant, user])
    try:
        await db_session.flush()
        db_session.add(TenantUser(tenant_id=tenant.id, user_id=user.id, role="owner"))
        await db_session.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered",
        ) from exc

    return RegisterResponse(userId=user.id, tenantId=tenant.id, email=user.email)


@router.post("/login", response_model=TokenResponse)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TokenResponse:
    email = normalize_email(form_data.username)
    result = await db_session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not verify_password_with_dummy(
        form_data.password, user.password_hash if user is not None else None
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )

    user.last_login_at = datetime.now(UTC)
    await db_session.flush()
    return TokenResponse(access_token=create_access_token(user.id))


@router.get("/me", response_model=CurrentUserResponse)
async def me(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user_context)],
) -> CurrentUserResponse:
    return CurrentUserResponse(
        userId=current_user.user.id,
        tenantId=current_user.tenant.id,
        email=current_user.user.email,
        isActive=current_user.user.is_active,
        createdAt=current_user.user.created_at,
        tenant={
            "id": current_user.tenant.id,
            "name": current_user.tenant.name,
            "role": current_user.role,
        },
    )
