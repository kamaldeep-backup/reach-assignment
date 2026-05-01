import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DeadLetterJob, Job, JobEvent, JobStatus
from app.services.quotas import release_runtime_slot, reserve_runtime_slot


@dataclass(frozen=True)
class ClaimedJob:
    id: uuid.UUID
    tenant_id: uuid.UUID
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
        .where(Job.status == JobStatus.PENDING, Job.run_after <= now)
        .order_by(Job.priority.desc(), Job.created_at.asc(), Job.id.asc())
        .with_for_update(skip_locked=True)
        .limit(candidate_limit)
    )

    for job in result.scalars().all():
        if not await reserve_runtime_slot(db_session=db_session, tenant_id=job.tenant_id):
            continue

        job.status = JobStatus.RUNNING
        job.attempts += 1
        job.locked_by = worker_id
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
        return ClaimedJob(
            id=job.id,
            tenant_id=job.tenant_id,
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
) -> bool:
    job = await _get_owned_running_job(
        db_session=db_session,
        job_id=job_id,
        worker_id=worker_id,
    )
    if job is None:
        return False

    now = datetime.now(UTC)
    await release_runtime_slot(db_session=db_session, tenant_id=job.tenant_id)
    job.status = JobStatus.SUCCEEDED
    job.locked_by = None
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
            event_metadata={"workerId": worker_id, "attempt": job.attempts},
        )
    )
    await db_session.flush()
    return True


async def schedule_job_retry(
    *,
    db_session: AsyncSession,
    job_id: uuid.UUID,
    worker_id: str,
    error: str,
    backoff_seconds: float,
) -> bool:
    job = await _get_owned_running_job(
        db_session=db_session,
        job_id=job_id,
        worker_id=worker_id,
    )
    if job is None:
        return False

    now = datetime.now(UTC)
    await release_runtime_slot(db_session=db_session, tenant_id=job.tenant_id)
    job.status = JobStatus.PENDING
    job.locked_by = None
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
    return True


async def move_owned_job_to_dlq(
    *,
    db_session: AsyncSession,
    job_id: uuid.UUID,
    worker_id: str,
    error: str,
    event_type: str = "DEAD_LETTERED",
) -> bool:
    job = await _get_owned_running_job(
        db_session=db_session,
        job_id=job_id,
        worker_id=worker_id,
    )
    if job is None:
        return False

    await release_runtime_slot(db_session=db_session, tenant_id=job.tenant_id)
    await _move_locked_job_to_dlq(
        db_session=db_session,
        job=job,
        error=error,
        event_type=event_type,
        metadata={"workerId": worker_id, "attempt": job.attempts},
    )
    return True


async def recover_expired_leases(
    *,
    db_session: AsyncSession,
    batch_size: int,
    backoff_seconds: float,
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
                metadata={"attempt": job.attempts, "reason": "lease_expired"},
            )
            recovered.append(
                LeaseRecoveryResult(
                    job_id=job.id,
                    status=JobStatus.DEAD_LETTERED,
                    event_type="DEAD_LETTERED",
                )
            )
            continue

        job.status = JobStatus.PENDING
        job.locked_by = None
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
) -> Job | None:
    result = await db_session.execute(
        select(Job)
        .where(
            Job.id == job_id,
            Job.status == JobStatus.RUNNING,
            Job.locked_by == worker_id,
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
    job.status = JobStatus.DEAD_LETTERED
    job.locked_by = None
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
