import uuid

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.api.v1.dependencies import AuthenticatedAPIKey, get_api_key_context
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


async def register_and_login(
    client: AsyncClient,
    email: str = "admin@acme.com",
    tenant_name: str = "Acme Corp",
) -> str:
    password = "correct-horse-battery-staple"
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "tenantName": tenant_name},
    )
    token_response = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password},
    )
    return str(token_response.json()["access_token"])


@pytest.mark.anyio
async def test_create_api_key_returns_raw_key_once_and_stores_only_hash() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        missing_auth_response = await client.post(
            "/api/v1/api-keys",
            json={"name": "local curl client"},
        )
        token = await register_and_login(client)
        response = await client.post(
            "/api/v1/api-keys",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "  local curl client  ",
                "scopes": ["jobs:read", "jobs:write", "jobs:read"],
            },
        )

    assert missing_auth_response.status_code == 401
    assert response.status_code == 201
    body = response.json()
    assert uuid.UUID(body["apiKeyId"])
    assert body["name"] == "local curl client"
    assert body["scopes"] == ["jobs:read", "jobs:write"]
    assert body["apiKey"].startswith(f"{body['keyPrefix']}_")
    assert body["isActive"] is True
    assert body["revokedAt"] is None

    async with AsyncSessionLocal() as session:
        api_key = (await session.execute(select(APIKey))).scalar_one()

    assert api_key.key_hash.startswith("hmac_sha256$")
    assert api_key.key_hash != body["apiKey"]
    assert body["apiKey"] not in api_key.key_hash
    assert api_key.key_prefix == body["keyPrefix"]
    assert api_key.created_by_user_id is not None


@pytest.mark.anyio
async def test_list_and_get_api_keys_never_return_raw_key_values() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        token = await register_and_login(client)
        create_response = await client.post(
            "/api/v1/api-keys",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "local curl client"},
        )
        api_key_id = create_response.json()["apiKeyId"]

        list_response = await client.get(
            "/api/v1/api-keys",
            headers={"Authorization": f"Bearer {token}"},
        )
        get_response = await client.get(
            f"/api/v1/api-keys/{api_key_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert list_response.status_code == 200
    assert get_response.status_code == 200
    assert "apiKey" not in list_response.json()[0]
    assert "apiKey" not in get_response.json()
    assert list_response.json()[0]["apiKeyId"] == api_key_id
    assert get_response.json()["apiKeyId"] == api_key_id


@pytest.mark.anyio
async def test_revoke_api_key_marks_key_inactive_without_deleting_it() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        token = await register_and_login(client)
        create_response = await client.post(
            "/api/v1/api-keys",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "local curl client"},
        )
        api_key_id = create_response.json()["apiKeyId"]

        revoke_response = await client.delete(
            f"/api/v1/api-keys/{api_key_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        get_response = await client.get(
            f"/api/v1/api-keys/{api_key_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert revoke_response.status_code == 204
    assert get_response.status_code == 200
    assert get_response.json()["isActive"] is False
    assert get_response.json()["revokedAt"] is not None

    async with AsyncSessionLocal() as session:
        api_key = (await session.execute(select(APIKey))).scalar_one()
    assert api_key.is_active is False
    assert api_key.revoked_at is not None


@pytest.mark.anyio
async def test_api_keys_are_tenant_scoped() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        first_token = await register_and_login(client, "first@acme.com", "First Corp")
        second_token = await register_and_login(
            client, "second@acme.com", "Second Corp"
        )
        create_response = await client.post(
            "/api/v1/api-keys",
            headers={"Authorization": f"Bearer {first_token}"},
            json={"name": "first tenant key"},
        )
        api_key_id = create_response.json()["apiKeyId"]

        second_list_response = await client.get(
            "/api/v1/api-keys",
            headers={"Authorization": f"Bearer {second_token}"},
        )
        second_get_response = await client.get(
            f"/api/v1/api-keys/{api_key_id}",
            headers={"Authorization": f"Bearer {second_token}"},
        )
        second_delete_response = await client.delete(
            f"/api/v1/api-keys/{api_key_id}",
            headers={"Authorization": f"Bearer {second_token}"},
        )

    assert second_list_response.status_code == 200
    assert second_list_response.json() == []
    assert second_get_response.status_code == 404
    assert second_delete_response.status_code == 404


@pytest.mark.anyio
async def test_api_key_header_authentication_accepts_active_key_and_rejects_revoked_key() -> None:
    probe_app = FastAPI()

    @probe_app.get("/probe")
    async def probe(
        context: AuthenticatedAPIKey = Depends(get_api_key_context),
    ) -> dict[str, str]:
        return {"tenantId": str(context.tenant.id)}

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        token = await register_and_login(client)
        create_response = await client.post(
            "/api/v1/api-keys",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "direct client"},
        )
        body = create_response.json()
        raw_api_key = body["apiKey"]
        api_key_id = body["apiKeyId"]

    async with AsyncClient(
        transport=ASGITransport(app=probe_app),
        base_url="http://test",
    ) as client:
        missing_response = await client.get("/probe")
        valid_response = await client.get(
            "/probe",
            headers={"X-API-Key": raw_api_key},
        )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        await client.delete(
            f"/api/v1/api-keys/{api_key_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    async with AsyncClient(
        transport=ASGITransport(app=probe_app),
        base_url="http://test",
    ) as client:
        revoked_response = await client.get(
            "/probe",
            headers={"X-API-Key": raw_api_key},
        )

    assert missing_response.status_code == 401
    assert valid_response.status_code == 200
    assert uuid.UUID(valid_response.json()["tenantId"])
    assert revoked_response.status_code == 403
    assert revoked_response.json() == {"detail": "Inactive API key"}
