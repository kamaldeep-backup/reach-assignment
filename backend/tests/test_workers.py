import asyncio
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
import uuid

import pytest
from sqlalchemy import delete, func, select

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
from app.repositories.worker_jobs import (
    ClaimedJob,
    claim_pending_job,
    mark_job_succeeded,
    move_owned_job_to_dlq,
    schedule_job_retry,
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
    lease_id: uuid.UUID | None = None,
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
            lease_id=lease_id,
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
    assert stored_job.lease_id == claimed.lease_id
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
    assert stored_job.lease_id == first_claim.lease_id
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
    assert stored_job.lease_id is None
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
    assert stored_job.lease_id is None
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
    assert processed is not None
    async with AsyncSessionLocal() as session:
        async with session.begin():
            second_dlq_move = await move_owned_job_to_dlq(
                db_session=session,
                job_id=job.id,
                worker_id="worker-1",
                lease_id=processed.lease_id,
                error="duplicate terminal update",
            )

    async with AsyncSessionLocal() as session:
        stored_job = await session.get(Job, job.id)
        quota = await session.get(TenantRuntimeQuota, tenant.id)
        dead_letters = (
            await session.execute(select(DeadLetterJob).where(DeadLetterJob.job_id == job.id))
        ).scalars().all()

    assert second_dlq_move is False
    assert stored_job is not None
    assert stored_job.status == JobStatus.DEAD_LETTERED
    assert stored_job.attempts == 3
    assert stored_job.lease_id is None
    assert quota is not None
    assert quota.running_jobs == 0
    assert len(dead_letters) == 1
    assert dead_letters[0].attempts == 3


@pytest.mark.anyio
async def test_unknown_job_type_is_non_retryable_dead_letter() -> None:
    _tenant, job = await create_tenant_and_job(job_type="missing")

    processed = await process_one_job(settings=worker_settings())

    async with AsyncSessionLocal() as session:
        stored_job = await session.get(Job, job.id)
        dead_letter = (
            await session.execute(select(DeadLetterJob).where(DeadLetterJob.job_id == job.id))
        ).scalar_one()

    assert processed is not None
    assert stored_job is not None
    assert stored_job.status == JobStatus.DEAD_LETTERED
    assert stored_job.lease_id is None
    assert "Unknown job type" in (stored_job.last_error or "")
    assert dead_letter.final_error == stored_job.last_error


@pytest.mark.anyio
async def test_quota_limit_prevents_over_claiming_without_failing_job() -> None:
    busy_lease_id = uuid.uuid4()
    tenant, running_job = await create_tenant_and_job(
        max_running_jobs=1,
        status=JobStatus.RUNNING,
        locked_by="busy-worker",
        lease_id=busy_lease_id,
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
async def test_default_worker_candidates_skip_saturated_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WORKER_BATCH_SIZE", raising=False)
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as session:
        saturated_tenant = Tenant(name="Saturated", max_running_jobs=1)
        available_tenant = Tenant(name="Available", max_running_jobs=1)
        session.add_all([saturated_tenant, available_tenant])
        await session.flush()
        session.add_all(
            [
                TenantRuntimeQuota(
                    tenant_id=saturated_tenant.id,
                    running_jobs=1,
                ),
                TenantRuntimeQuota(tenant_id=available_tenant.id),
            ]
        )
        saturated_running_job = Job(
            tenant_id=saturated_tenant.id,
            idempotency_key="saturated-running",
            job_type="noop",
            payload={"ok": True},
            status=JobStatus.RUNNING,
            locked_by="busy-worker",
            lease_id=uuid.uuid4(),
            lease_expires_at=now + timedelta(minutes=1),
            created_at=now - timedelta(minutes=3),
        )
        saturated_pending_jobs = [
            Job(
                tenant_id=saturated_tenant.id,
                idempotency_key=f"saturated-pending-{index}",
                job_type="noop",
                payload={"ok": True},
                run_after=now - timedelta(seconds=1),
                created_at=now - timedelta(minutes=2) + timedelta(seconds=index),
            )
            for index in range(10)
        ]
        available_pending_job = Job(
            tenant_id=available_tenant.id,
            idempotency_key="available-pending",
            job_type="noop",
            payload={"ok": True},
            run_after=now - timedelta(seconds=1),
            created_at=now - timedelta(minutes=1),
        )
        session.add_all(
            [saturated_running_job, *saturated_pending_jobs, available_pending_job]
        )
        await session.commit()
        saturated_pending_job_ids = [job.id for job in saturated_pending_jobs]

    settings = WorkerSettings(
        worker_id="worker-1",
        worker_lease_seconds=60,
        worker_base_backoff_seconds=2,
        worker_max_backoff_seconds=60,
        worker_jitter_seconds=0,
        lease_reaper_batch_size=50,
        _env_file=None,
    )
    processed = await process_one_job(settings=settings)

    async with AsyncSessionLocal() as session:
        saturated_pending_statuses = (
            await session.execute(
                select(Job.status).where(Job.id.in_(saturated_pending_job_ids))
            )
        ).scalars().all()
        stored_available_pending = await session.get(Job, available_pending_job.id)
        saturated_quota = await session.get(TenantRuntimeQuota, saturated_tenant.id)
        available_quota = await session.get(TenantRuntimeQuota, available_tenant.id)

    assert settings.worker_batch_size == 10
    assert processed is not None
    assert processed.id == available_pending_job.id
    assert saturated_pending_statuses == [JobStatus.PENDING] * 10
    assert stored_available_pending is not None
    assert stored_available_pending.status == JobStatus.SUCCEEDED
    assert saturated_quota is not None
    assert saturated_quota.running_jobs == 1
    assert available_quota is not None
    assert available_quota.running_jobs == 0


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
async def test_owned_updates_require_current_lease_token() -> None:
    tenant, job = await create_tenant_and_job()

    async with AsyncSessionLocal() as session:
        async with session.begin():
            claimed = await claim_pending_job(
                db_session=session,
                worker_id="worker-1",
                lease_seconds=30,
            )

    assert claimed is not None
    wrong_lease_id = uuid.uuid4()
    async with AsyncSessionLocal() as session:
        async with session.begin():
            stale_success = await mark_job_succeeded(
                db_session=session,
                job_id=job.id,
                worker_id="worker-1",
                lease_id=wrong_lease_id,
            )
            stale_retry = await schedule_job_retry(
                db_session=session,
                job_id=job.id,
                worker_id="worker-1",
                lease_id=wrong_lease_id,
                error="wrong lease",
                backoff_seconds=2,
            )
            stale_dlq = await move_owned_job_to_dlq(
                db_session=session,
                job_id=job.id,
                worker_id="worker-1",
                lease_id=wrong_lease_id,
                error="wrong lease",
            )

    async with AsyncSessionLocal() as session:
        stored_job = await session.get(Job, job.id)
        quota = await session.get(TenantRuntimeQuota, tenant.id)

    assert stale_success is False
    assert stale_retry is False
    assert stale_dlq is False
    assert stored_job is not None
    assert stored_job.status == JobStatus.RUNNING
    assert stored_job.locked_by == "worker-1"
    assert stored_job.lease_id == claimed.lease_id
    assert quota is not None
    assert quota.running_jobs == 1

    async with AsyncSessionLocal() as session:
        async with session.begin():
            current_success = await mark_job_succeeded(
                db_session=session,
                job_id=job.id,
                worker_id="worker-1",
                lease_id=claimed.lease_id,
            )

    assert current_success is True
    async with AsyncSessionLocal() as session:
        stored_job = await session.get(Job, job.id)
        quota = await session.get(TenantRuntimeQuota, tenant.id)

    assert stored_job is not None
    assert stored_job.status == JobStatus.SUCCEEDED
    assert stored_job.lease_id is None
    assert quota is not None
    assert quota.running_jobs == 0


@pytest.mark.anyio
async def test_owned_updates_reject_expired_lease_even_with_current_token() -> None:
    lease_id = uuid.uuid4()
    tenant, job = await create_tenant_and_job(
        status=JobStatus.RUNNING,
        attempts=1,
        locked_by="worker-1",
        lease_id=lease_id,
        lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    async with AsyncSessionLocal() as session:
        quota = await session.get(TenantRuntimeQuota, tenant.id)
        assert quota is not None
        quota.running_jobs = 1
        await session.commit()

    async with AsyncSessionLocal() as session:
        async with session.begin():
            stale_success = await mark_job_succeeded(
                db_session=session,
                job_id=job.id,
                worker_id="worker-1",
                lease_id=lease_id,
            )

    async with AsyncSessionLocal() as session:
        stored_job = await session.get(Job, job.id)
        quota = await session.get(TenantRuntimeQuota, tenant.id)

    assert stale_success is False
    assert stored_job is not None
    assert stored_job.status == JobStatus.RUNNING
    assert stored_job.lease_id == lease_id
    assert quota is not None
    assert quota.running_jobs == 1


@pytest.mark.anyio
async def test_stale_same_worker_lease_cannot_ack_reclaimed_job() -> None:
    tenant, job = await create_tenant_and_job()

    async with AsyncSessionLocal() as session:
        async with session.begin():
            first_claim = await claim_pending_job(
                db_session=session,
                worker_id="worker-1",
                lease_seconds=30,
            )

    assert first_claim is not None
    async with AsyncSessionLocal() as session:
        async with session.begin():
            stored_job = await session.get(Job, job.id)
            assert stored_job is not None
            stored_job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)

    recovered = await recover_once(settings=worker_settings())
    assert len(recovered) == 1

    async with AsyncSessionLocal() as session:
        async with session.begin():
            stored_job = await session.get(Job, job.id)
            assert stored_job is not None
            stored_job.run_after = datetime.now(UTC) - timedelta(seconds=1)

    async with AsyncSessionLocal() as session:
        async with session.begin():
            second_claim = await claim_pending_job(
                db_session=session,
                worker_id="worker-1",
                lease_seconds=30,
            )

    assert second_claim is not None
    assert second_claim.id == first_claim.id
    assert second_claim.lease_id != first_claim.lease_id

    async with AsyncSessionLocal() as session:
        async with session.begin():
            stale_ack = await mark_job_succeeded(
                db_session=session,
                job_id=job.id,
                worker_id="worker-1",
                lease_id=first_claim.lease_id,
            )

    async with AsyncSessionLocal() as session:
        stored_job = await session.get(Job, job.id)
        quota = await session.get(TenantRuntimeQuota, tenant.id)

    assert stale_ack is False
    assert stored_job is not None
    assert stored_job.status == JobStatus.RUNNING
    assert stored_job.locked_by == "worker-1"
    assert stored_job.lease_id == second_claim.lease_id
    assert quota is not None
    assert quota.running_jobs == 1

    async with AsyncSessionLocal() as session:
        async with session.begin():
            current_ack = await mark_job_succeeded(
                db_session=session,
                job_id=job.id,
                worker_id="worker-1",
                lease_id=second_claim.lease_id,
            )

    assert current_ack is True


@pytest.mark.anyio
async def test_lease_reaper_requeues_expired_leases_and_rejects_stale_ack() -> None:
    stale_lease_id = uuid.uuid4()
    tenant, job = await create_tenant_and_job(
        status=JobStatus.RUNNING,
        attempts=1,
        max_attempts=3,
        locked_by="stale-worker",
        lease_id=stale_lease_id,
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
                lease_id=stale_lease_id,
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
    assert stored_job.lease_id is None
    assert stored_job.run_after > datetime.now(UTC)
    assert quota is not None
    assert quota.running_jobs == 0
    assert sorted(event_types) == ["LEASE_EXPIRED", "REQUEUED_FROM_TIMEOUT"]


@pytest.mark.anyio
async def test_lease_reaper_uses_expired_job_attempts_for_backoff() -> None:
    tenant, job = await create_tenant_and_job(
        status=JobStatus.RUNNING,
        attempts=2,
        max_attempts=3,
        locked_by="stale-worker",
        lease_id=uuid.uuid4(),
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
        retry_event = (
            await session.execute(
                select(JobEvent).where(
                    JobEvent.job_id == job.id,
                    JobEvent.event_type == "REQUEUED_FROM_TIMEOUT",
                )
            )
        ).scalar_one()

    assert len(recovered) == 1
    assert stored_job is not None
    assert stored_job.status == JobStatus.PENDING
    assert stored_job.run_after - stored_job.updated_at == timedelta(seconds=4)
    assert retry_event.event_metadata["backoffSeconds"] == 4


@pytest.mark.anyio
async def test_lease_reaper_dead_letters_exhausted_expired_leases() -> None:
    tenant, job = await create_tenant_and_job(
        status=JobStatus.RUNNING,
        attempts=3,
        max_attempts=3,
        locked_by="stale-worker",
        lease_id=uuid.uuid4(),
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
    assert stored_job.lease_id is None
    assert quota is not None
    assert quota.running_jobs == 0
    assert dead_letter.attempts == 3


@pytest.mark.anyio
async def test_multiple_workers_preserve_lease_uniqueness_and_tenant_quotas_under_load() -> None:
    now = datetime.now(UTC)
    tenant_limits = [1, 2, 3]
    jobs_per_tenant = 8
    total_jobs = len(tenant_limits) * jobs_per_tenant
    stress_jobs: list[Job] = []

    async with AsyncSessionLocal() as session:
        tenants = [
            Tenant(name=f"Stress Tenant {index}", max_running_jobs=max_running_jobs)
            for index, max_running_jobs in enumerate(tenant_limits, start=1)
        ]
        session.add_all(tenants)
        await session.flush()

        session.add_all(
            TenantRuntimeQuota(tenant_id=tenant.id) for tenant in tenants
        )
        for tenant in tenants:
            for job_index in range(jobs_per_tenant):
                job = Job(
                    tenant_id=tenant.id,
                    idempotency_key=f"stress-{tenant.id}-{job_index}",
                    job_type="noop",
                    payload={"jobIndex": job_index},
                    run_after=now - timedelta(seconds=1),
                    created_at=now + timedelta(milliseconds=job_index),
                )
                session.add(job)
                stress_jobs.append(job)
        await session.commit()
        quota_by_tenant_id = {
            tenant.id: tenant.max_running_jobs for tenant in tenants
        }
        stress_job_ids = {job.id for job in stress_jobs}

    active_by_tenant_id: defaultdict[uuid.UUID, int] = defaultdict(int)
    max_active_by_tenant_id: defaultdict[uuid.UUID, int] = defaultdict(int)
    processed_job_ids: list[uuid.UUID] = []
    claimed_lease_ids: list[uuid.UUID] = []
    tracker_lock = asyncio.Lock()
    registry = HandlerRegistry()

    async def tracked_noop(job: ClaimedJob) -> None:
        tenant_id = job.tenant_id
        async with tracker_lock:
            active_by_tenant_id[tenant_id] += 1
            max_active_by_tenant_id[tenant_id] = max(
                max_active_by_tenant_id[tenant_id],
                active_by_tenant_id[tenant_id],
            )

        await asyncio.sleep(0.01)

        async with tracker_lock:
            active_by_tenant_id[tenant_id] -= 1
            processed_job_ids.append(job.id)
            claimed_lease_ids.append(job.lease_id)

    registry.register("noop", tracked_noop)

    async def unfinished_job_count() -> int:
        async with AsyncSessionLocal() as session:
            return int(
                await session.scalar(
                    select(func.count())
                    .select_from(Job)
                    .where(
                        Job.id.in_(stress_job_ids),
                        Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
                    )
                )
                or 0
            )

    async def worker_loop(worker_index: int) -> None:
        settings = worker_settings(worker_id=f"stress-worker-{worker_index}")
        while True:
            processed = await process_one_job(settings=settings, registry=registry)
            if processed is not None:
                continue
            if await unfinished_job_count() == 0:
                return
            await asyncio.sleep(0.005)

    await asyncio.gather(*(worker_loop(index) for index in range(8)))

    async with AsyncSessionLocal() as session:
        jobs = (
            await session.execute(select(Job).where(Job.id.in_(stress_job_ids)))
        ).scalars().all()
        quotas = (
            await session.execute(
                select(TenantRuntimeQuota).where(
                    TenantRuntimeQuota.tenant_id.in_(quota_by_tenant_id.keys())
                )
            )
        ).scalars().all()
        events = (
            await session.execute(
                select(JobEvent).where(
                    JobEvent.job_id.in_(stress_job_ids),
                    JobEvent.event_type.in_(["CLAIMED", "SUCCEEDED"])
                )
            )
        ).scalars().all()

    event_counts_by_job_id: defaultdict[uuid.UUID, Counter[str]] = defaultdict(Counter)
    for event in events:
        event_counts_by_job_id[event.job_id][event.event_type] += 1

    assert len(jobs) == total_jobs
    terminal_errors = {
        str(job.id): job.last_error
        for job in jobs
        if job.status != JobStatus.SUCCEEDED
    }
    assert terminal_errors == {}
    assert {job.lease_id for job in jobs} == {None}
    assert len(processed_job_ids) == total_jobs
    assert len(set(processed_job_ids)) == total_jobs
    assert len(claimed_lease_ids) == total_jobs
    assert len(set(claimed_lease_ids)) == total_jobs
    assert {quota.running_jobs for quota in quotas} == {0}
    for tenant_id, max_running_jobs in quota_by_tenant_id.items():
        assert max_active_by_tenant_id[tenant_id] <= max_running_jobs
    for job in jobs:
        assert event_counts_by_job_id[job.id] == Counter({"CLAIMED": 1, "SUCCEEDED": 1})
