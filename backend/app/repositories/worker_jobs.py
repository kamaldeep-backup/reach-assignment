import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DeadLetterJob,
    Job,
    JobEvent,
    JobStatus,
    Tenant,
    TenantRuntimeQuota,
)
from app.observability.metrics import (
    record_job_claimed,
    record_job_dead_lettered,
    record_job_lease_expired,
    record_job_retried,
    record_job_succeeded,
)
from app.services.quotas import release_runtime_slot, reserve_runtime_slot


@dataclass(frozen=True)
class ClaimedJob:
    id: uuid.UUID
    tenant_id: uuid.UUID
    lease_id: uuid.UUID
    job_type: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int


@dataclass(frozen=True)
class LeaseRecoveryResult:
    job_id: uuid.UUID
    status: JobStatus
    event_type: str


async def claim_pending_job(
    *,
    db_session: AsyncSession,
    worker_id: str,
    lease_seconds: int,
    candidate_limit: int = 10,
) -> ClaimedJob | None:
    now = datetime.now(UTC)
    result = await db_session.execute(
        select(Job)
        .join(Tenant, Tenant.id == Job.tenant_id)
        .outerjoin(TenantRuntimeQuota, TenantRuntimeQuota.tenant_id == Job.tenant_id)
        .where(
            Job.status == JobStatus.PENDING,
            Job.run_after <= now,
            func.coalesce(TenantRuntimeQuota.running_jobs, 0) < Tenant.max_running_jobs,
        )
        .order_by(Job.priority.desc(), Job.created_at.asc(), Job.id.asc())
        .with_for_update(skip_locked=True, of=Job)
        .limit(candidate_limit)
    )

    for job in result.scalars().all():
        if not await reserve_runtime_slot(db_session=db_session, tenant_id=job.tenant_id):
            continue

        lease_id = uuid.uuid4()
        job.status = JobStatus.RUNNING
        job.attempts += 1
        job.locked_by = worker_id
        job.lease_id = lease_id
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        job.updated_at = now
        db_session.add(
            JobEvent(
                job_id=job.id,
                tenant_id=job.tenant_id,
                event_type="CLAIMED",
                from_status=JobStatus.PENDING,
                to_status=JobStatus.RUNNING,
                message="Job claimed by worker",
                event_metadata={
                    "workerId": worker_id,
                    "attempt": job.attempts,
                    "leaseSeconds": lease_seconds,
                },
            )
        )
        await db_session.flush()
        record_job_claimed(
            tenant_id=job.tenant_id,
            worker_id=worker_id,
            job_type=job.job_type,
            created_at=job.created_at,
            claimed_at=now,
        )
        return ClaimedJob(
            id=job.id,
            tenant_id=job.tenant_id,
            lease_id=lease_id,
            job_type=job.job_type,
            payload=job.payload,
            attempts=job.attempts,
            max_attempts=job.max_attempts,
        )

    return None


async def mark_job_succeeded(
    *,
    db_session: AsyncSession,
    job_id: uuid.UUID,
    worker_id: str,
    lease_id: uuid.UUID,
) -> bool:
    job = await _get_owned_running_job(
        db_session=db_session,
        job_id=job_id,
        worker_id=worker_id,
        lease_id=lease_id,
    )
    if job is None:
        return False

    now = datetime.now(UTC)
    claimed_at = job.updated_at
    await release_runtime_slot(db_session=db_session, tenant_id=job.tenant_id)
    job.status = JobStatus.SUCCEEDED
    job.locked_by = None
    job.lease_id = None
    job.lease_expires_at = None
    job.completed_at = now
    job.updated_at = now
    db_session.add(
        JobEvent(
            job_id=job.id,
            tenant_id=job.tenant_id,
            event_type="SUCCEEDED",
            from_status=JobStatus.RUNNING,
            to_status=JobStatus.SUCCEEDED,
            message="Job completed successfully",
            event_metadata={
                "workerId": worker_id,
                "attempt": job.attempts,
            },
        )
    )
    await db_session.flush()
    record_job_succeeded(
        tenant_id=job.tenant_id,
        worker_id=worker_id,
        job_type=job.job_type,
        claimed_at=claimed_at,
        completed_at=now,
    )
    return True


async def schedule_job_retry(
    *,
    db_session: AsyncSession,
    job_id: uuid.UUID,
    worker_id: str,
    lease_id: uuid.UUID,
    error: str,
    backoff_seconds: float,
) -> bool:
    job = await _get_owned_running_job(
        db_session=db_session,
        job_id=job_id,
        worker_id=worker_id,
        lease_id=lease_id,
    )
    if job is None:
        return False

    now = datetime.now(UTC)
    claimed_at = job.updated_at
    await release_runtime_slot(db_session=db_session, tenant_id=job.tenant_id)
    job.status = JobStatus.PENDING
    job.locked_by = None
    job.lease_id = None
    job.lease_expires_at = None
    job.run_after = now + timedelta(seconds=backoff_seconds)
    job.last_error = error
    job.updated_at = now
    db_session.add(
        JobEvent(
            job_id=job.id,
            tenant_id=job.tenant_id,
            event_type="FAILED_RETRY_SCHEDULED",
            from_status=JobStatus.RUNNING,
            to_status=JobStatus.PENDING,
            message="Job failed and was scheduled for retry",
            event_metadata={
                "workerId": worker_id,
                "attempt": job.attempts,
                "backoffSeconds": backoff_seconds,
            },
        )
    )
    await db_session.flush()
    record_job_retried(
        tenant_id=job.tenant_id,
        job_type=job.job_type,
        claimed_at=claimed_at,
        finished_at=now,
    )
    return True


async def move_owned_job_to_dlq(
    *,
    db_session: AsyncSession,
    job_id: uuid.UUID,
    worker_id: str,
    lease_id: uuid.UUID,
    error: str,
    event_type: str = "DEAD_LETTERED",
) -> bool:
    job = await _get_owned_running_job(
        db_session=db_session,
        job_id=job_id,
        worker_id=worker_id,
        lease_id=lease_id,
    )
    if job is None:
        return False

    await release_runtime_slot(db_session=db_session, tenant_id=job.tenant_id)
    await _move_locked_job_to_dlq(
        db_session=db_session,
        job=job,
        error=error,
        event_type=event_type,
        metadata={
            "workerId": worker_id,
            "attempt": job.attempts,
        },
    )
    return True


async def recover_expired_leases(
    *,
    db_session: AsyncSession,
    batch_size: int,
    backoff_seconds_for_attempt: Callable[[int], float],
) -> list[LeaseRecoveryResult]:
    now = datetime.now(UTC)
    result = await db_session.execute(
        select(Job)
        .where(Job.status == JobStatus.RUNNING, Job.lease_expires_at < now)
        .order_by(Job.lease_expires_at.asc(), Job.id.asc())
        .with_for_update(skip_locked=True)
        .limit(batch_size)
    )

    recovered: list[LeaseRecoveryResult] = []
    for job in result.scalars().all():
        await release_runtime_slot(db_session=db_session, tenant_id=job.tenant_id)
        record_job_lease_expired(job.tenant_id)
        db_session.add(
            JobEvent(
                job_id=job.id,
                tenant_id=job.tenant_id,
                event_type="LEASE_EXPIRED",
                from_status=JobStatus.RUNNING,
                to_status=JobStatus.RUNNING,
                message="Job lease expired before worker acknowledgement",
                event_metadata={
                    "workerId": job.locked_by,
                    "attempt": job.attempts,
                    "leaseExpiredAt": job.lease_expires_at.isoformat()
                    if job.lease_expires_at
                    else None,
                },
            )
        )

        if job.attempts >= job.max_attempts:
            await _move_locked_job_to_dlq(
                db_session=db_session,
                job=job,
                error="Worker lease expired and attempts were exhausted",
                event_type="DEAD_LETTERED",
                metadata={
                    "workerId": job.locked_by,
                    "attempt": job.attempts,
                    "reason": "lease_expired",
                },
            )
            recovered.append(
                LeaseRecoveryResult(
                    job_id=job.id,
                    status=JobStatus.DEAD_LETTERED,
                    event_type="DEAD_LETTERED",
                )
            )
            continue

        backoff_seconds = backoff_seconds_for_attempt(job.attempts)
        job.status = JobStatus.PENDING
        job.locked_by = None
        job.lease_id = None
        job.lease_expires_at = None
        job.run_after = now + timedelta(seconds=backoff_seconds)
        job.last_error = "Worker lease expired before acknowledgement"
        job.updated_at = now
        db_session.add(
            JobEvent(
                job_id=job.id,
                tenant_id=job.tenant_id,
                event_type="REQUEUED_FROM_TIMEOUT",
                from_status=JobStatus.RUNNING,
                to_status=JobStatus.PENDING,
                message="Expired lease recovered and job requeued",
                event_metadata={
                    "attempt": job.attempts,
                    "backoffSeconds": backoff_seconds,
                },
            )
        )
        recovered.append(
            LeaseRecoveryResult(
                job_id=job.id,
                status=JobStatus.PENDING,
                event_type="REQUEUED_FROM_TIMEOUT",
            )
        )

    await db_session.flush()
    return recovered


async def _get_owned_running_job(
    *,
    db_session: AsyncSession,
    job_id: uuid.UUID,
    worker_id: str,
    lease_id: uuid.UUID,
) -> Job | None:
    now = datetime.now(UTC)
    result = await db_session.execute(
        select(Job)
        .where(
            Job.id == job_id,
            Job.status == JobStatus.RUNNING,
            Job.locked_by == worker_id,
            Job.lease_id == lease_id,
            Job.lease_expires_at.is_not(None),
            Job.lease_expires_at > now,
        )
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def _move_locked_job_to_dlq(
    *,
    db_session: AsyncSession,
    job: Job,
    error: str,
    event_type: str,
    metadata: dict[str, Any],
) -> None:
    now = datetime.now(UTC)
    claimed_at = job.updated_at
    job.status = JobStatus.DEAD_LETTERED
    job.locked_by = None
    job.lease_id = None
    job.lease_expires_at = None
    job.last_error = error
    job.completed_at = now
    job.updated_at = now
    await db_session.execute(
        insert(DeadLetterJob)
        .values(
            job_id=job.id,
            tenant_id=job.tenant_id,
            payload=job.payload,
            final_error=error,
            attempts=job.attempts,
        )
        .on_conflict_do_nothing(index_elements=[DeadLetterJob.job_id])
    )
    db_session.add(
        JobEvent(
            job_id=job.id,
            tenant_id=job.tenant_id,
            event_type=event_type,
            from_status=JobStatus.RUNNING,
            to_status=JobStatus.DEAD_LETTERED,
            message="Job moved to dead letter queue",
            event_metadata=metadata,
        )
    )
    await db_session.flush()
    record_job_dead_lettered(
        tenant_id=job.tenant_id,
        job_type=job.job_type,
        claimed_at=claimed_at,
        finished_at=now,
    )
