import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal, dispose_database_engine
from app.main import app
from app.models import APIKey, Tenant, TenantUser, User


@pytest.fixture(autouse=True)
async def clean_auth_tables() -> None:
    await dispose_database_engine()
    async with AsyncSessionLocal() as session:
        for model in (APIKey, TenantUser, User, Tenant):
            await session.execute(delete(model))
        await session.commit()
    yield
    async with AsyncSessionLocal() as session:
        for model in (APIKey, TenantUser, User, Tenant):
            await session.execute(delete(model))
        await session.commit()
    await dispose_database_engine()


@pytest.mark.anyio
async def test_register_creates_user_tenant_and_owner_membership() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "Admin@Acme.com",
                "password": "correct-horse-battery-staple",
                "tenantName": "Acme Corp",
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "admin@acme.com"
    assert uuid.UUID(body["userId"])
    assert uuid.UUID(body["tenantId"])
    assert "password" not in body

    async with AsyncSessionLocal() as session:
        user = (
            await session.execute(select(User).where(User.email == "admin@acme.com"))
        ).scalar_one()
        tenant = (
            await session.execute(select(Tenant).where(Tenant.name == "Acme Corp"))
        ).scalar_one()
        membership = (
            await session.execute(
                select(TenantUser).where(
                    TenantUser.user_id == user.id,
                    TenantUser.tenant_id == tenant.id,
                )
            )
        ).scalar_one()

    assert user.password_hash != "correct-horse-battery-staple"
    assert user.password_hash.startswith("$argon2")
    assert membership.role == "owner"


@pytest.mark.anyio
async def test_register_rejects_duplicate_email() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        payload = {
            "email": "admin@acme.com",
            "password": "correct-horse-battery-staple",
            "tenantName": "Acme Corp",
        }
        first_response = await client.post("/api/v1/auth/register", json=payload)
        second_response = await client.post("/api/v1/auth/register", json=payload)

    assert first_response.status_code == 201
    assert second_response.status_code == 409
    assert second_response.json() == {"detail": "Email is already registered"}


@pytest.mark.anyio
async def test_register_rejects_blank_tenant_name() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "admin@acme.com",
                "password": "correct-horse-battery-staple",
                "tenantName": "   ",
            },
        )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_login_returns_bearer_token_for_valid_credentials() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "admin@acme.com",
                "password": "correct-horse-battery-staple",
                "tenantName": "Acme Corp",
            },
        )

        response = await client.post(
            "/api/v1/auth/login",
            data={
                "username": "ADMIN@ACME.COM",
                "password": "correct-horse-battery-staple",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]

    async with AsyncSessionLocal() as session:
        user = (
            await session.execute(select(User).where(User.email == "admin@acme.com"))
        ).scalar_one()
    assert user.last_login_at is not None


@pytest.mark.anyio
async def test_login_rejects_invalid_credentials() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/auth/login",
            data={"username": "missing@acme.com", "password": "wrong-password"},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "Incorrect email or password"}
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.anyio
async def test_me_returns_current_user_and_tenant_from_access_token() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        register_response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "admin@acme.com",
                "password": "correct-horse-battery-staple",
                "tenantName": "Acme Corp",
            },
        )
        token_response = await client.post(
            "/api/v1/auth/login",
            data={
                "username": "admin@acme.com",
                "password": "correct-horse-battery-staple",
            },
        )
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token_response.json()['access_token']}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["userId"] == register_response.json()["userId"]
    assert body["tenantId"] == register_response.json()["tenantId"]
    assert body["email"] == "admin@acme.com"
    assert body["isActive"] is True
    assert body["tenant"]["name"] == "Acme Corp"
    assert body["tenant"]["role"] == "owner"


@pytest.mark.anyio
async def test_me_rejects_missing_or_invalid_access_token() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        missing_response = await client.get("/api/v1/auth/me")
        invalid_response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid-token"},
        )

    assert missing_response.status_code == 401
    assert invalid_response.status_code == 401
    assert invalid_response.json() == {"detail": "Could not validate credentials"}
