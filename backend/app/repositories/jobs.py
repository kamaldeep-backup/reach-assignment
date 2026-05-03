import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job, JobEvent, JobStatus


async def get_job_by_idempotency_key(
    *,
    db_session: AsyncSession,
    tenant_id: uuid.UUID,
    idempotency_key: str,
) -> Job | None:
    result = await db_session.execute(
        select(Job).where(
            Job.tenant_id == tenant_id,
            Job.idempotency_key == idempotency_key,
        )
    )
    return result.scalar_one_or_none()


async def get_tenant_job(
    *,
    db_session: AsyncSession,
    tenant_id: uuid.UUID,
    job_id: uuid.UUID,
) -> Job | None:
    result = await db_session.execute(
        select(Job).where(Job.id == job_id, Job.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


async def list_tenant_jobs(
    *,
    db_session: AsyncSession,
    tenant_id: uuid.UUID,
    status_filter: JobStatus | None,
    limit: int,
    offset: int,
) -> list[Job]:
    conditions = [Job.tenant_id == tenant_id]
    if status_filter is not None:
        conditions.append(Job.status == status_filter)

    result = await db_session.execute(
        select(Job)
        .where(*conditions)
        .order_by(Job.created_at.desc(), Job.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all())


async def count_tenant_jobs(
    *,
    db_session: AsyncSession,
    tenant_id: uuid.UUID,
    status_filter: JobStatus | None,
) -> int:
    conditions = [Job.tenant_id == tenant_id]
    if status_filter is not None:
        conditions.append(Job.status == status_filter)

    result = await db_session.execute(
        select(func.count()).select_from(Job).where(*conditions)
    )
    return int(result.scalar_one())


async def create_job(
    *,
    db_session: AsyncSession,
    tenant_id: uuid.UUID,
    idempotency_key: str,
    job_type: str,
    payload: dict[str, Any],
    priority: int,
) -> Job:
    job = Job(
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        job_type=job_type,
        payload=payload,
        priority=priority,
    )
    db_session.add(job)
    await db_session.flush()
    return job


async def refresh_job(*, db_session: AsyncSession, job: Job) -> Job:
    await db_session.refresh(job)
    return job


async def create_job_event(
    *,
    db_session: AsyncSession,
    job: Job,
    event_type: str,
    from_status: JobStatus | None,
    to_status: JobStatus | None,
    message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> JobEvent:
    event = JobEvent(
        job_id=job.id,
        tenant_id=job.tenant_id,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        message=message,
        event_metadata=metadata or {},
    )
    db_session.add(event)
    await db_session.flush()
    return event


async def list_job_events(
    *,
    db_session: AsyncSession,
    tenant_id: uuid.UUID,
    job_id: uuid.UUID,
) -> list[JobEvent]:
    result = await db_session.execute(
        select(JobEvent)
        .where(
            JobEvent.job_id == job_id,
            JobEvent.tenant_id == tenant_id,
        )
        .order_by(JobEvent.created_at.asc(), JobEvent.id.asc())
    )
    return list(result.scalars().all())


async def list_tenant_job_events_after(
    *,
    db_session: AsyncSession,
    tenant_id: uuid.UUID,
    after_created_at: datetime,
    after_event_id: uuid.UUID,
    limit: int,
) -> list[tuple[JobEvent, Job]]:
    result = await db_session.execute(
        select(JobEvent, Job)
        .join(Job, Job.id == JobEvent.job_id)
        .where(
            JobEvent.tenant_id == tenant_id,
            or_(
                JobEvent.created_at > after_created_at,
                and_(
                    JobEvent.created_at == after_created_at,
                    JobEvent.id > after_event_id,
                ),
            ),
        )
        .order_by(JobEvent.created_at.asc(), JobEvent.id.asc())
        .limit(limit)
    )
    return list(result.all())
