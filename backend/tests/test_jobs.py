import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select, text, update

from app.core.database import AsyncSessionLocal, dispose_database_engine
from app.main import app
from app.models import (
    APIKey,
    Job,
    JobEvent,
    JobStatus,
    Tenant,
    TenantSubmissionRateLimit,
    TenantUser,
    User,
)


@pytest.fixture(autouse=True)
async def clean_tables() -> None:
    await dispose_database_engine()
    async with AsyncSessionLocal() as session:
        for model in (
            JobEvent,
            Job,
            TenantSubmissionRateLimit,
            APIKey,
            TenantUser,
            User,
            Tenant,
        ):
            await session.execute(delete(model))
        await session.commit()
    yield
    async with AsyncSessionLocal() as session:
        for model in (
            JobEvent,
            Job,
            TenantSubmissionRateLimit,
            APIKey,
            TenantUser,
            User,
            Tenant,
        ):
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


async def create_api_key(
    client: AsyncClient,
    token: str,
    scopes: list[str] | None = None,
) -> str:
    response = await client.post(
        "/api/v1/api-keys",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "direct client", "scopes": scopes or ["jobs:read", "jobs:write"]},
    )
    return str(response.json()["apiKey"])


async def create_job(
    client: AsyncClient,
    token: str,
    idempotency_key: str,
    job_type: str = "send_email",
) -> dict:
    response = await client.post(
        "/api/v1/jobs",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": idempotency_key,
        },
        json={
            "type": job_type,
            "payload": {"to": "customer@example.com", "template": "welcome"},
            "priority": 10,
        },
    )
    assert response.status_code == 202
    return response.json()


@pytest.mark.anyio
async def test_create_job_requires_auth_and_idempotency_then_records_submission() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        token = await register_and_login(client)
        missing_auth_response = await client.post(
            "/api/v1/jobs",
            headers={"Idempotency-Key": "job-1"},
            json={"type": "send_email", "payload": {"to": "customer@example.com"}},
        )
        missing_idempotency_response = await client.post(
            "/api/v1/jobs",
            headers={"Authorization": f"Bearer {token}"},
            json={"type": "send_email", "payload": {"to": "customer@example.com"}},
        )
        create_response = await client.post(
            "/api/v1/jobs",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": "job-1",
            },
            json={
                "type": "  send_email  ",
                "payload": {"to": "customer@example.com"},
                "priority": 5,
            },
        )
        duplicate_response = await client.post(
            "/api/v1/jobs",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": "job-1",
            },
            json={
                "type": "different",
                "payload": {"ignored": True},
                "priority": 100,
            },
        )

    assert missing_auth_response.status_code == 401
    assert missing_idempotency_response.status_code == 422
    assert create_response.status_code == 202
    body = create_response.json()
    assert uuid.UUID(body["jobId"])
    assert body["idempotencyKey"] == "job-1"
    assert body["type"] == "send_email"
    assert body["status"] == "PENDING"
    assert body["priority"] == 5
    assert duplicate_response.status_code == 202
    assert duplicate_response.json()["jobId"] == body["jobId"]
    assert duplicate_response.json()["type"] == "send_email"

    async with AsyncSessionLocal() as session:
        job_count = await session.scalar(select(func.count()).select_from(Job))
        event = (await session.execute(select(JobEvent))).scalar_one()

    assert job_count == 1
    assert event.event_type == "SUBMITTED"
    assert event.to_status == JobStatus.PENDING


@pytest.mark.anyio
async def test_create_job_enforces_tenant_submit_rate_limit() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        token = await register_and_login(client)
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(Tenant)
                .where(Tenant.name == "Acme Corp")
                .values(submit_rate_limit=2)
            )
            await session.commit()

        first_response = await client.post(
            "/api/v1/jobs",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": "limited-1",
            },
            json={"type": "send_email", "payload": {"to": "customer@example.com"}},
        )
        second_response = await client.post(
            "/api/v1/jobs",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": "limited-2",
            },
            json={"type": "send_email", "payload": {"to": "customer@example.com"}},
        )
        duplicate_response = await client.post(
            "/api/v1/jobs",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": "limited-1",
            },
            json={"type": "ignored", "payload": {"ignored": True}},
        )
        limited_response = await client.post(
            "/api/v1/jobs",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": "limited-3",
            },
            json={"type": "send_email", "payload": {"to": "customer@example.com"}},
        )

    assert first_response.status_code == 202
    assert second_response.status_code == 202
    assert duplicate_response.status_code == 202
    assert duplicate_response.json()["jobId"] == first_response.json()["jobId"]
    assert limited_response.status_code == 429
    assert limited_response.json()["detail"] == "Tenant submission rate limit exceeded"
    assert 1 <= int(limited_response.headers["Retry-After"]) <= 60

    async with AsyncSessionLocal() as session:
        job_count = await session.scalar(select(func.count()).select_from(Job))
        counter = (await session.execute(select(TenantSubmissionRateLimit))).scalar_one()

    assert job_count == 2
    assert counter.submitted_count == 2


@pytest.mark.anyio
async def test_tenant_submit_rate_limit_resets_on_next_fixed_window() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        token = await register_and_login(client)
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(Tenant)
                .where(Tenant.name == "Acme Corp")
                .values(submit_rate_limit=1)
            )
            await session.commit()

        first_response = await client.post(
            "/api/v1/jobs",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": "window-1",
            },
            json={"type": "send_email", "payload": {"to": "customer@example.com"}},
        )
        limited_response = await client.post(
            "/api/v1/jobs",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": "window-2",
            },
            json={"type": "send_email", "payload": {"to": "customer@example.com"}},
        )

        async with AsyncSessionLocal() as session:
            await session.execute(
                update(TenantSubmissionRateLimit).values(
                    window_start=func.now() - text("interval '1 minute'")
                )
            )
            await session.commit()

        next_window_response = await client.post(
            "/api/v1/jobs",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": "window-2",
            },
            json={"type": "send_email", "payload": {"to": "customer@example.com"}},
        )

    assert first_response.status_code == 202
    assert limited_response.status_code == 429
    assert next_window_response.status_code == 202

    async with AsyncSessionLocal() as session:
        job_count = await session.scalar(select(func.count()).select_from(Job))
        counter = (await session.execute(select(TenantSubmissionRateLimit))).scalar_one()

    assert job_count == 2
    assert counter.submitted_count == 1


@pytest.mark.anyio
async def test_list_get_and_events_are_tenant_scoped() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        first_token = await register_and_login(client, "first@acme.com", "First")
        second_token = await register_and_login(client, "second@acme.com", "Second")
        first_job = await create_job(client, first_token, "first-1", "first")
        await create_job(client, first_token, "first-2", "first")
        await create_job(client, first_token, "first-3", "first")
        await create_job(client, second_token, "second-1", "second")

        list_response = await client.get(
            "/api/v1/jobs",
            headers={"Authorization": f"Bearer {first_token}"},
            params={"limit": 2, "status": "PENDING"},
        )
        get_response = await client.get(
            f"/api/v1/jobs/{first_job['jobId']}",
            headers={"Authorization": f"Bearer {first_token}"},
        )
        events_response = await client.get(
            f"/api/v1/jobs/{first_job['jobId']}/events",
            headers={"Authorization": f"Bearer {first_token}"},
        )
        cross_tenant_response = await client.get(
            f"/api/v1/jobs/{first_job['jobId']}",
            headers={"Authorization": f"Bearer {second_token}"},
        )

    assert list_response.status_code == 200
    list_body = list_response.json()
    assert len(list_body["items"]) == 2
    assert list_body["total"] == 3
    assert list_body["limit"] == 2
    assert list_body["offset"] == 0
    assert list_body["hasMore"] is True
    assert "nextCursor" not in list_body
    assert get_response.status_code == 200
    assert get_response.json()["jobId"] == first_job["jobId"]
    assert events_response.status_code == 200
    assert events_response.json()[0]["eventType"] == "SUBMITTED"
    assert cross_tenant_response.status_code == 404


@pytest.mark.anyio
async def test_list_jobs_supports_offset_pagination() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        token = await register_and_login(client)
        for index in range(5):
            await create_job(client, token, f"job-{index}")

        first_page_response = await client.get(
            "/api/v1/jobs",
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": 2, "offset": 0},
        )
        second_page_response = await client.get(
            "/api/v1/jobs",
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": 2, "offset": 2},
        )
        final_page_response = await client.get(
            "/api/v1/jobs",
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": 2, "offset": 4},
        )

    assert first_page_response.status_code == 200
    first_page = first_page_response.json()
    assert len(first_page["items"]) == 2
    assert first_page["total"] == 5
    assert first_page["limit"] == 2
    assert first_page["offset"] == 0
    assert first_page["hasMore"] is True

    second_page = second_page_response.json()
    assert len(second_page["items"]) == 2
    assert second_page["total"] == 5
    assert second_page["offset"] == 2
    assert second_page["hasMore"] is True
    assert {job["jobId"] for job in first_page["items"]}.isdisjoint(
        {job["jobId"] for job in second_page["items"]}
    )

    final_page = final_page_response.json()
    assert len(final_page["items"]) == 1
    assert final_page["total"] == 5
    assert final_page["offset"] == 4
    assert final_page["hasMore"] is False


@pytest.mark.anyio
async def test_mutable_job_crud_endpoints_are_not_exposed() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        token = await register_and_login(client)
        job = await create_job(client, token, "immutable-job")
        headers = {"Authorization": f"Bearer {token}"}

        patch_response = await client.patch(
            f"/api/v1/jobs/{job['jobId']}",
            headers=headers,
            json={"priority": 1},
        )
        delete_response = await client.delete(
            f"/api/v1/jobs/{job['jobId']}",
            headers=headers,
        )
        cancel_response = await client.post(
            f"/api/v1/jobs/{job['jobId']}/cancel",
            headers=headers,
        )

    assert patch_response.status_code == 405
    assert delete_response.status_code == 405
    assert cancel_response.status_code == 404


@pytest.mark.anyio
async def test_api_key_authentication_enforces_jobs_scopes() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        token = await register_and_login(client)
        read_only_key = await create_api_key(client, token, ["jobs:read"])
        write_only_key = await create_api_key(client, token, ["jobs:write"])
        full_key = await create_api_key(client, token)
        job = await create_job(client, token, "bearer-created-job")

        read_only_create_response = await client.post(
            "/api/v1/jobs",
            headers={"X-API-Key": read_only_key, "Idempotency-Key": "read-only"},
            json={"type": "send_email", "payload": {"to": "customer@example.com"}},
        )
        write_only_get_response = await client.get(
            f"/api/v1/jobs/{job['jobId']}",
            headers={"X-API-Key": write_only_key},
        )
        full_key_get_response = await client.get(
            f"/api/v1/jobs/{job['jobId']}",
            headers={"X-API-Key": full_key},
        )
        full_key_create_response = await client.post(
            "/api/v1/jobs",
            headers={"X-API-Key": full_key, "Idempotency-Key": "api-key-job"},
            json={"type": "send_email", "payload": {"to": "customer@example.com"}},
        )

    assert read_only_create_response.status_code == 403
    assert write_only_get_response.status_code == 403
    assert full_key_get_response.status_code == 200
    assert full_key_get_response.json()["jobId"] == job["jobId"]
    assert full_key_create_response.status_code == 202


@pytest.mark.anyio
async def test_create_job_rejects_oversized_request_body() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        token = await register_and_login(client)
        response = await client.post(
            "/api/v1/jobs",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": "oversized",
                "Content-Length": str(64 * 1024 + 1),
            },
            json={"type": "send_email", "payload": {"to": "customer@example.com"}},
        )

    assert response.status_code == 413
