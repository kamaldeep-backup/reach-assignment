from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal, dispose_database_engine
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
from app.repositories.users import create_user_with_tenant


@pytest.fixture(autouse=True)
async def clean_worker_schema_tables() -> None:
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


@pytest.mark.anyio
async def test_new_tenants_have_worker_defaults_and_runtime_quota() -> None:
    async with AsyncSessionLocal() as session:
        user, tenant, _membership = await create_user_with_tenant(
            db_session=session,
            email="admin@acme.com",
            password_hash="hashed-password",
            tenant_name="Acme",
        )
        await session.commit()

        quota = await session.get(TenantRuntimeQuota, tenant.id)
        await session.refresh(tenant)
        await session.refresh(user)

    assert tenant.max_running_jobs == 5
    assert tenant.submit_rate_limit == 60
    assert quota is not None
    assert quota.running_jobs == 0


@pytest.mark.anyio
async def test_jobs_have_worker_queue_fields_and_dead_letter_status() -> None:
    async with AsyncSessionLocal() as session:
        tenant = Tenant(name="Acme")
        session.add(tenant)
        await session.flush()
        job = Job(
            tenant_id=tenant.id,
            idempotency_key="job-1",
            job_type="noop",
            payload={"ok": True},
        )
        session.add(job)
        await session.commit()

        await session.refresh(job)

    assert job.status == JobStatus.PENDING
    assert job.attempts == 0
    assert job.max_attempts == 3
    assert job.run_after <= datetime.now(UTC)
    assert job.lease_expires_at is None
    assert job.locked_by is None
    assert JobStatus.DEAD_LETTERED.value == "DEAD_LETTERED"


@pytest.mark.anyio
async def test_dead_letter_jobs_preserve_terminal_failure_context() -> None:
    async with AsyncSessionLocal() as session:
        tenant = Tenant(name="Acme")
        session.add(tenant)
        await session.flush()
        payload = {"to": "customer@example.com", "template": "welcome"}
        job = Job(
            tenant_id=tenant.id,
            idempotency_key="job-1",
            job_type="send_email",
            payload=payload,
            status=JobStatus.DEAD_LETTERED,
            attempts=3,
            max_attempts=3,
            last_error="SMTP permanently rejected the request",
            completed_at=datetime.now(UTC),
            run_after=datetime.now(UTC) - timedelta(seconds=1),
        )
        session.add(job)
        await session.flush()
        dead_letter = DeadLetterJob(
            job_id=job.id,
            tenant_id=tenant.id,
            payload=payload,
            final_error="SMTP permanently rejected the request",
            attempts=3,
        )
        session.add(dead_letter)
        await session.commit()

        stored_dead_letter = (
            await session.execute(select(DeadLetterJob).where(DeadLetterJob.job_id == job.id))
        ).scalar_one()

    assert stored_dead_letter.payload == payload
    assert stored_dead_letter.final_error == "SMTP permanently rejected the request"
    assert stored_dead_letter.attempts == 3
