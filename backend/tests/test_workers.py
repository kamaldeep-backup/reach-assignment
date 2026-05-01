from datetime import UTC, datetime, timedelta
import uuid

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
    TenantUser,
    User,
)
from app.repositories.worker_jobs import (
    claim_pending_job,
    mark_job_succeeded,
    move_owned_job_to_dlq,
)
from app.workers.lease_reaper import recover_once
from app.workers.handlers import HandlerRegistry, RetryableJobError
from app.workers.settings import WorkerSettings
from app.workers.worker import process_one_job


@pytest.fixture(autouse=True)
async def clean_worker_tables() -> None:
    await dispose_database_engine()
    async with AsyncSessionLocal() as session:
        for model in (
            DeadLetterJob,
            JobEvent,
            Job,
            TenantRuntimeQuota,
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
            APIKey,
            TenantUser,
            User,
            Tenant,
        ):
            await session.execute(delete(model))
        await session.commit()
    await dispose_database_engine()


def worker_settings(worker_id: str = "worker-1") -> WorkerSettings:
    return WorkerSettings(
        worker_id=worker_id,
        worker_lease_seconds=60,
        worker_batch_size=10,
        worker_base_backoff_seconds=2,
        worker_max_backoff_seconds=60,
        worker_jitter_seconds=0,
        lease_reaper_batch_size=50,
    )


async def create_tenant_and_job(
    *,
    job_type: str = "noop",
    max_running_jobs: int = 5,
    attempts: int = 0,
    max_attempts: int = 3,
    run_after: datetime | None = None,
    status: JobStatus = JobStatus.PENDING,
    locked_by: str | None = None,
    lease_expires_at: datetime | None = None,
) -> tuple[Tenant, Job]:
    async with AsyncSessionLocal() as session:
        tenant = Tenant(name="Acme", max_running_jobs=max_running_jobs)
        session.add(tenant)
        await session.flush()
        session.add(TenantRuntimeQuota(tenant_id=tenant.id))
        job = Job(
            tenant_id=tenant.id,
            idempotency_key=f"job-{uuid.uuid4()}",
            job_type=job_type,
            payload={"to": "customer@example.com", "url": "https://example.com"},
            attempts=attempts,
            max_attempts=max_attempts,
            run_after=run_after or datetime.now(UTC) - timedelta(seconds=1),
            status=status,
            locked_by=locked_by,
            lease_expires_at=lease_expires_at,
        )
        session.add(job)
        await session.commit()
        await session.refresh(tenant)
        await session.refresh(job)
        return tenant, job


@pytest.mark.anyio
async def test_claim_pending_job_marks_running_and_records_event() -> None:
    tenant, job = await create_tenant_and_job()

    async with AsyncSessionLocal() as session:
        async with session.begin():
            claimed = await claim_pending_job(
                db_session=session,
                worker_id="worker-1",
                lease_seconds=30,
            )

    async with AsyncSessionLocal() as session:
        stored_job = await session.get(Job, job.id)
        quota = await session.get(TenantRuntimeQuota, tenant.id)
        events = (
            await session.execute(select(JobEvent).where(JobEvent.job_id == job.id))
        ).scalars().all()

    assert claimed is not None
    assert claimed.id == job.id
    assert stored_job is not None
    assert stored_job.status == JobStatus.RUNNING
    assert stored_job.attempts == 1
    assert stored_job.locked_by == "worker-1"
    assert stored_job.lease_expires_at is not None
    assert quota is not None
    assert quota.running_jobs == 1
    assert [event.event_type for event in events] == ["CLAIMED"]


@pytest.mark.anyio
async def test_two_workers_cannot_claim_same_pending_job_concurrently() -> None:
    _tenant, job = await create_tenant_and_job()

    first_session = AsyncSessionLocal()
    second_session = AsyncSessionLocal()
    first_transaction = first_session.begin()
    second_transaction = second_session.begin()
    await first_transaction.__aenter__()
    await second_transaction.__aenter__()
    try:
        first_claim = await claim_pending_job(
            db_session=first_session,
            worker_id="worker-1",
            lease_seconds=30,
        )
        second_claim = await claim_pending_job(
            db_session=second_session,
            worker_id="worker-2",
            lease_seconds=30,
        )
    finally:
        await second_transaction.__aexit__(None, None, None)
        await first_transaction.__aexit__(None, None, None)
        await second_session.close()
        await first_session.close()

    async with AsyncSessionLocal() as session:
        stored_job = await session.get(Job, job.id)
        claim_events = (
            await session.execute(
                select(JobEvent).where(
                    JobEvent.job_id == job.id,
                    JobEvent.event_type == "CLAIMED",
                )
            )
        ).scalars().all()

    assert first_claim is not None
    assert second_claim is None
    assert stored_job is not None
    assert stored_job.locked_by == "worker-1"
    assert len(claim_events) == 1


@pytest.mark.anyio
async def test_successful_handler_marks_succeeded_and_releases_quota() -> None:
    tenant, job = await create_tenant_and_job(job_type="noop")

    processed = await process_one_job(settings=worker_settings())

    async with AsyncSessionLocal() as session:
        stored_job = await session.get(Job, job.id)
        quota = await session.get(TenantRuntimeQuota, tenant.id)
        event_types = (
            await session.execute(
                select(JobEvent.event_type)
                .where(JobEvent.job_id == job.id)
                .order_by(JobEvent.created_at.asc(), JobEvent.id.asc())
            )
        ).scalars().all()

    assert processed is not None
    assert stored_job is not None
    assert stored_job.status == JobStatus.SUCCEEDED
    assert stored_job.completed_at is not None
    assert stored_job.locked_by is None
    assert stored_job.lease_expires_at is None
    assert quota is not None
    assert quota.running_jobs == 0
    assert event_types == ["CLAIMED", "SUCCEEDED"]


@pytest.mark.anyio
async def test_retryable_failure_requeues_with_backoff_and_releases_quota() -> None:
    tenant, job = await create_tenant_and_job(job_type="fail_once")

    processed = await process_one_job(settings=worker_settings())

    async with AsyncSessionLocal() as session:
        stored_job = await session.get(Job, job.id)
        quota = await session.get(TenantRuntimeQuota, tenant.id)
        retry_event = (
            await session.execute(
                select(JobEvent).where(
                    JobEvent.job_id == job.id,
                    JobEvent.event_type == "FAILED_RETRY_SCHEDULED",
                )
            )
        ).scalar_one()

    assert processed is not None
    assert stored_job is not None
    assert stored_job.status == JobStatus.PENDING
    assert stored_job.attempts == 1
    assert stored_job.run_after > datetime.now(UTC)
    assert "Intentional first-attempt failure" in (stored_job.last_error or "")
    assert quota is not None
    assert quota.running_jobs == 0
    assert retry_event.event_metadata["backoffSeconds"] == 2


@pytest.mark.anyio
async def test_exhausted_retry_moves_to_dlq_and_dlq_insert_is_idempotent() -> None:
    tenant, job = await create_tenant_and_job(
        job_type="always_retry",
        attempts=2,
        max_attempts=3,
    )
    registry = HandlerRegistry()

    async def always_retry(_job: object) -> None:
        raise RetryableJobError("transient failure persisted")

    registry.register("always_retry", always_retry)

    processed = await process_one_job(settings=worker_settings(), registry=registry)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            second_dlq_move = await move_owned_job_to_dlq(
                db_session=session,
                job_id=job.id,
                worker_id="worker-1",
                error="duplicate terminal update",
            )

    async with AsyncSessionLocal() as session:
        stored_job = await session.get(Job, job.id)
        quota = await session.get(TenantRuntimeQuota, tenant.id)
        dead_letters = (
            await session.execute(select(DeadLetterJob).where(DeadLetterJob.job_id == job.id))
        ).scalars().all()

    assert processed is not None
    assert second_dlq_move is False
    assert stored_job is not None
    assert stored_job.status == JobStatus.DEAD_LETTERED
    assert stored_job.attempts == 3
    assert quota is not None
    assert quota.running_jobs == 0
    assert len(dead_letters) == 1
    assert dead_letters[0].attempts == 3


@pytest.mark.anyio
async def test_unknown_job_type_is_non_retryable_dead_letter() -> None:
    _tenant, job = await create_tenant_and_job(job_type="missing")

    await process_one_job(settings=worker_settings())

    async with AsyncSessionLocal() as session:
        stored_job = await session.get(Job, job.id)
        dead_letter = (
            await session.execute(select(DeadLetterJob).where(DeadLetterJob.job_id == job.id))
        ).scalar_one()

    assert stored_job is not None
    assert stored_job.status == JobStatus.DEAD_LETTERED
    assert "Unknown job type" in (stored_job.last_error or "")
    assert dead_letter.final_error == stored_job.last_error


@pytest.mark.anyio
async def test_quota_limit_prevents_over_claiming_without_failing_job() -> None:
    tenant, running_job = await create_tenant_and_job(
        max_running_jobs=1,
        status=JobStatus.RUNNING,
        locked_by="busy-worker",
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    async with AsyncSessionLocal() as session:
        pending_job = Job(
            tenant_id=tenant.id,
            idempotency_key="pending-quota-job",
            job_type="noop",
            payload={"ok": True},
            run_after=datetime.now(UTC) - timedelta(seconds=1),
        )
        session.add(pending_job)
        quota = await session.get(TenantRuntimeQuota, tenant.id)
        assert quota is not None
        quota.running_jobs = 1
        await session.commit()
        await session.refresh(pending_job)

    async with AsyncSessionLocal() as session:
        async with session.begin():
            claimed = await claim_pending_job(
                db_session=session,
                worker_id="worker-1",
                lease_seconds=30,
            )

    async with AsyncSessionLocal() as session:
        stored_running_job = await session.get(Job, running_job.id)
        stored_pending_job = await session.get(Job, pending_job.id)
        quota = await session.get(TenantRuntimeQuota, tenant.id)

    assert claimed is None
    assert stored_running_job is not None
    assert stored_running_job.status == JobStatus.RUNNING
    assert stored_pending_job is not None
    assert stored_pending_job.status == JobStatus.PENDING
    assert quota is not None
    assert quota.running_jobs == 1


@pytest.mark.anyio
async def test_future_run_after_jobs_are_not_claimed() -> None:
    _tenant, job = await create_tenant_and_job(
        run_after=datetime.now(UTC) + timedelta(minutes=5)
    )

    async with AsyncSessionLocal() as session:
        async with session.begin():
            claimed = await claim_pending_job(
                db_session=session,
                worker_id="worker-1",
                lease_seconds=30,
            )

    async with AsyncSessionLocal() as session:
        stored_job = await session.get(Job, job.id)

    assert claimed is None
    assert stored_job is not None
    assert stored_job.status == JobStatus.PENDING


@pytest.mark.anyio
async def test_lease_reaper_requeues_expired_leases_and_rejects_stale_ack() -> None:
    tenant, job = await create_tenant_and_job(
        status=JobStatus.RUNNING,
        attempts=1,
        max_attempts=3,
        locked_by="stale-worker",
        lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    async with AsyncSessionLocal() as session:
        quota = await session.get(TenantRuntimeQuota, tenant.id)
        assert quota is not None
        quota.running_jobs = 1
        await session.commit()

    recovered = await recover_once(settings=worker_settings())
    async with AsyncSessionLocal() as session:
        async with session.begin():
            stale_ack = await mark_job_succeeded(
                db_session=session,
                job_id=job.id,
                worker_id="stale-worker",
            )

    async with AsyncSessionLocal() as session:
        stored_job = await session.get(Job, job.id)
        quota = await session.get(TenantRuntimeQuota, tenant.id)
        event_types = (
            await session.execute(
                select(JobEvent.event_type)
                .where(JobEvent.job_id == job.id)
                .order_by(JobEvent.created_at.asc(), JobEvent.id.asc())
            )
        ).scalars().all()

    assert len(recovered) == 1
    assert stale_ack is False
    assert stored_job is not None
    assert stored_job.status == JobStatus.PENDING
    assert stored_job.locked_by is None
    assert stored_job.run_after > datetime.now(UTC)
    assert quota is not None
    assert quota.running_jobs == 0
    assert sorted(event_types) == ["LEASE_EXPIRED", "REQUEUED_FROM_TIMEOUT"]


@pytest.mark.anyio
async def test_lease_reaper_dead_letters_exhausted_expired_leases() -> None:
    tenant, job = await create_tenant_and_job(
        status=JobStatus.RUNNING,
        attempts=3,
        max_attempts=3,
        locked_by="stale-worker",
        lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    async with AsyncSessionLocal() as session:
        quota = await session.get(TenantRuntimeQuota, tenant.id)
        assert quota is not None
        quota.running_jobs = 1
        await session.commit()

    recovered = await recover_once(settings=worker_settings())

    async with AsyncSessionLocal() as session:
        stored_job = await session.get(Job, job.id)
        quota = await session.get(TenantRuntimeQuota, tenant.id)
        dead_letter = (
            await session.execute(select(DeadLetterJob).where(DeadLetterJob.job_id == job.id))
        ).scalar_one()

    assert len(recovered) == 1
    assert stored_job is not None
    assert stored_job.status == JobStatus.DEAD_LETTERED
    assert quota is not None
    assert quota.running_jobs == 0
    assert dead_letter.attempts == 3
