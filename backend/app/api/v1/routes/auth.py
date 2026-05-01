from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import AuthenticatedUser, get_current_user_context
from app.core.database import get_db_session
from app.repositories import users as users_repository
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
    try:
        user, tenant, _membership = await users_repository.create_user_with_tenant(
            db_session=db_session,
            email=email,
            password_hash=hash_password(request.password),
            tenant_name=request.tenant_name,
        )
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
    user = await users_repository.get_user_by_email(
        db_session=db_session,
        email=email,
    )

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

    await users_repository.update_last_login_at(
        db_session=db_session,
        user=user,
        last_login_at=datetime.now(UTC),
    )
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
            "maxRunningJobs": current_user.tenant.max_running_jobs,
            "submitRateLimit": current_user.tenant.submit_rate_limit,
        },
    )
