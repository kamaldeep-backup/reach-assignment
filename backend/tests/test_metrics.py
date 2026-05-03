from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal, dispose_database_engine
from app.main import app
from app.models import (
    APIKey,
    DeadLetterJob,
    Job,
    JobEvent,
    JobStatus,
    Tenant,
    TenantRuntimeQuota,
    TenantSubmissionRateLimit,
    TenantUser,
    User,
)


@pytest.fixture(autouse=True)
async def clean_metrics_tables() -> None:
    await dispose_database_engine()
    async with AsyncSessionLocal() as session:
        for model in (
            DeadLetterJob,
            JobEvent,
            Job,
            TenantRuntimeQuota,
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
            DeadLetterJob,
            JobEvent,
            Job,
            TenantRuntimeQuota,
            TenantSubmissionRateLimit,
            APIKey,
            TenantUser,
            User,
            Tenant,
        ):
            await session.execute(delete(model))
        await session.commit()
    await dispose_database_engine()


async def register_and_login(client: AsyncClient) -> tuple[str, Tenant]:
    password = "correct-horse-battery-staple"
    await client.post(
        "/api/v1/auth/register",
        json={"email": "metrics@acme.com", "password": password, "tenantName": "Acme"},
    )
    token_response = await client.post(
        "/api/v1/auth/login",
        data={"username": "metrics@acme.com", "password": password},
    )
    async with AsyncSessionLocal() as session:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.name == "Acme"))
        ).scalar_one()
    return str(token_response.json()["access_token"]), tenant


async def seed_jobs(tenant: Tenant) -> None:
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as session:
        jobs: list[Job] = []
        for index in range(120):
            jobs.append(
                Job(
                    tenant_id=tenant.id,
                    idempotency_key=f"pending-{index}",
                    job_type="send_email",
                    payload={"index": index},
                    status=JobStatus.PENDING,
                    created_at=now - timedelta(seconds=90 + index),
                )
            )

        jobs.extend(
            [
                Job(
                    tenant_id=tenant.id,
                    idempotency_key=f"running-{index}",
                    job_type="send_email",
                    payload={"index": index},
                    status=JobStatus.RUNNING,
                    locked_by="worker-1",
                    lease_expires_at=now + timedelta(seconds=30),
                )
                for index in range(3)
            ]
        )
        jobs.extend(
            [
                Job(
                    tenant_id=tenant.id,
                    idempotency_key=f"succeeded-{index}",
                    job_type="send_email",
                    payload={"index": index},
                    status=JobStatus.SUCCEEDED,
                    completed_at=now,
                )
                for index in range(4)
            ]
        )
        failed_job = Job(
            tenant_id=tenant.id,
            idempotency_key="failed-1",
            job_type="send_email",
            payload={"ok": False},
            status=JobStatus.FAILED,
        )
        dead_lettered_job = Job(
            tenant_id=tenant.id,
            idempotency_key="dead-lettered-1",
            job_type="send_email",
            payload={"ok": False},
            status=JobStatus.DEAD_LETTERED,
            completed_at=now,
        )
        jobs.extend([failed_job, dead_lettered_job])
        session.add_all(jobs)
        await session.flush()
        session.add_all(
            [
                JobEvent(
                    tenant_id=tenant.id,
                    job_id=jobs[0].id,
                    event_type="SUBMITTED",
                    to_status=JobStatus.PENDING,
                    event_metadata={},
                ),
                JobEvent(
                    tenant_id=tenant.id,
                    job_id=jobs[120].id,
                    event_type="CLAIMED",
                    from_status=JobStatus.PENDING,
                    to_status=JobStatus.RUNNING,
                    event_metadata={"workerId": "worker-1"},
                ),
            ]
        )
        session.add(
            DeadLetterJob(
                tenant_id=tenant.id,
                job_id=dead_lettered_job.id,
                payload=dead_lettered_job.payload,
                final_error="handler failed permanently",
                attempts=3,
            )
        )
        await session.commit()


@pytest.mark.anyio
async def test_metrics_summary_returns_authoritative_tenant_counts() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        token, tenant = await register_and_login(client)
        await seed_jobs(tenant)

        response = await client.get(
            "/api/v1/metrics/summary",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["pending"] == 120
    assert body["queueDepth"] == 120
    assert body["running"] == 3
    assert body["succeeded"] == 4
    assert body["failed"] == 1
    assert body["deadLettered"] == 1
    assert body["oldestPendingAgeSeconds"] >= 90
    assert body["runningLimit"] == tenant.max_running_jobs


@pytest.mark.anyio
async def test_prometheus_metrics_endpoint_is_unauthenticated_and_db_backed() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        _token, tenant = await register_and_login(client)
        await seed_jobs(tenant)

        response = await client.get("/metrics")

    assert response.status_code == 200
    body = response.text
    assert "queue_depth" in body
    assert "dead_letter_jobs" in body
    assert f'tenant_id="{tenant.id}"' in body
    assert 'status="PENDING"' in body
    assert 'worker_id="worker-1"' in body
    assert "jobs_claimed_total" in body
    assert " 120.0" in body
