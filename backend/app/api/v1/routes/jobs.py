import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import (
    AuthenticatedTenant,
    get_current_tenant_context,
    require_api_key_scope,
)
from app.core.database import get_db_session
from app.models import Job, JobEvent, JobStatus
from app.schemas import (
    JobCreateRequest,
    JobEventResponse,
    JobListResponse,
    JobResponse,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])

MAX_JOB_BODY_BYTES = 64 * 1024


async def enforce_job_body_size(request: Request) -> None:
    content_length = request.headers.get("content-length")
    if content_length is None:
        return
    try:
        body_size = int(content_length)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Content-Length header",
        ) from exc
    if body_size > MAX_JOB_BODY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Job request body is too large",
        )


def serialize_job(job: Job) -> JobResponse:
    return JobResponse(
        jobId=job.id,
        idempotencyKey=job.idempotency_key,
        type=job.job_type,
        payload=job.payload,
        status=job.status,
        priority=job.priority,
        lastError=job.last_error,
        createdAt=job.created_at,
        updatedAt=job.updated_at,
        completedAt=job.completed_at,
    )


def serialize_event(event: JobEvent) -> JobEventResponse:
    return JobEventResponse(
        eventId=event.id,
        jobId=event.job_id,
        eventType=event.event_type,
        fromStatus=event.from_status,
        toStatus=event.to_status,
        message=event.message,
        metadata=event.event_metadata,
        createdAt=event.created_at,
    )


def record_job_event(
    *,
    db_session: AsyncSession,
    job: Job,
    event_type: str,
    from_status: JobStatus | None,
    to_status: JobStatus | None,
    message: str | None = None,
    metadata: dict | None = None,
) -> None:
    db_session.add(
        JobEvent(
            job_id=job.id,
            tenant_id=job.tenant_id,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            message=message,
            event_metadata=metadata or {},
        )
    )


async def get_tenant_job_or_404(
    *,
    job_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db_session: AsyncSession,
) -> Job:
    result = await db_session.execute(
        select(Job).where(Job.id == job_id, Job.tenant_id == tenant_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )
    return job


@router.post(
    "",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(enforce_job_body_size)],
)
async def create_job(
    request: JobCreateRequest,
    current_context: Annotated[AuthenticatedTenant, Depends(get_current_tenant_context)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=200),
    ],
) -> JobResponse:
    require_api_key_scope(current_context, "jobs:write")
    idempotency_key = idempotency_key.strip()
    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Idempotency-Key cannot be blank",
        )

    tenant_id = current_context.tenant.id
    existing_result = await db_session.execute(
        select(Job).where(
            Job.tenant_id == tenant_id,
            Job.idempotency_key == idempotency_key,
        )
    )
    existing_job = existing_result.scalar_one_or_none()
    if existing_job is not None:
        return serialize_job(existing_job)

    job = Job(
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        job_type=request.job_type,
        payload=request.payload,
        priority=request.priority,
    )
    db_session.add(job)
    try:
        await db_session.flush()
    except IntegrityError:
        await db_session.rollback()
        existing_result = await db_session.execute(
            select(Job).where(
                Job.tenant_id == tenant_id,
                Job.idempotency_key == idempotency_key,
            )
        )
        existing_job = existing_result.scalar_one_or_none()
        if existing_job is not None:
            return serialize_job(existing_job)
        raise
    record_job_event(
        db_session=db_session,
        job=job,
        event_type="SUBMITTED",
        from_status=None,
        to_status=JobStatus.PENDING,
        message="Job submitted",
    )
    await db_session.flush()
    await db_session.refresh(job)
    return serialize_job(job)


@router.get("", response_model=JobListResponse)
async def list_jobs(
    current_context: Annotated[AuthenticatedTenant, Depends(get_current_tenant_context)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    status_filter: Annotated[JobStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> JobListResponse:
    require_api_key_scope(current_context, "jobs:read")
    conditions = [Job.tenant_id == current_context.tenant.id]
    if status_filter is not None:
        conditions.append(Job.status == status_filter)

    result = await db_session.execute(
        select(Job)
        .where(*conditions)
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(limit)
    )
    jobs = list(result.scalars().all())
    return JobListResponse(items=[serialize_job(job) for job in jobs])


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: uuid.UUID,
    current_context: Annotated[AuthenticatedTenant, Depends(get_current_tenant_context)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> JobResponse:
    require_api_key_scope(current_context, "jobs:read")
    job = await get_tenant_job_or_404(
        job_id=job_id,
        tenant_id=current_context.tenant.id,
        db_session=db_session,
    )
    return serialize_job(job)


@router.get("/{job_id}/events", response_model=list[JobEventResponse])
async def list_job_events(
    job_id: uuid.UUID,
    current_context: Annotated[AuthenticatedTenant, Depends(get_current_tenant_context)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[JobEventResponse]:
    require_api_key_scope(current_context, "jobs:read")
    await get_tenant_job_or_404(
        job_id=job_id,
        tenant_id=current_context.tenant.id,
        db_session=db_session,
    )
    result = await db_session.execute(
        select(JobEvent)
        .where(
            JobEvent.job_id == job_id,
            JobEvent.tenant_id == current_context.tenant.id,
        )
        .order_by(JobEvent.created_at.asc(), JobEvent.id.asc())
    )
    return [serialize_event(event) for event in result.scalars().all()]
