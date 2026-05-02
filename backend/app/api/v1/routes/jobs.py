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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import (
    AuthenticatedTenant,
    get_current_tenant_context,
    require_api_key_scope,
)
from app.core.database import get_db_session
from app.models import Job, JobEvent, JobStatus
from app.repositories import jobs as jobs_repository
from app.schemas import (
    JobCreateRequest,
    JobEventResponse,
    JobListResponse,
    JobResponse,
)
from app.services.submission_rate_limits import reserve_submission_slot

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
        attempts=job.attempts,
        maxAttempts=job.max_attempts,
        runAfter=job.run_after,
        leaseExpiresAt=job.lease_expires_at,
        lockedBy=job.locked_by,
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


async def get_tenant_job_or_404(
    *,
    job_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db_session: AsyncSession,
) -> Job:
    job = await jobs_repository.get_tenant_job(
        db_session=db_session,
        tenant_id=tenant_id,
        job_id=job_id,
    )
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
    existing_job = await jobs_repository.get_job_by_idempotency_key(
        db_session=db_session,
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
    )
    if existing_job is not None:
        return serialize_job(existing_job)

    rate_limit_result = await reserve_submission_slot(
        db_session=db_session,
        tenant_id=tenant_id,
    )
    if not rate_limit_result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Tenant submission rate limit exceeded",
            headers={"Retry-After": str(rate_limit_result.retry_after_seconds or 60)},
        )

    try:
        job = await jobs_repository.create_job(
            db_session=db_session,
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            job_type=request.job_type,
            payload=request.payload,
            priority=request.priority,
        )
    except IntegrityError:
        await db_session.rollback()
        existing_job = await jobs_repository.get_job_by_idempotency_key(
            db_session=db_session,
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
        )
        if existing_job is not None:
            return serialize_job(existing_job)
        raise
    await jobs_repository.create_job_event(
        db_session=db_session,
        job=job,
        event_type="SUBMITTED",
        from_status=None,
        to_status=JobStatus.PENDING,
        message="Job submitted",
    )
    await jobs_repository.refresh_job(db_session=db_session, job=job)
    return serialize_job(job)


@router.get("", response_model=JobListResponse)
async def list_jobs(
    current_context: Annotated[AuthenticatedTenant, Depends(get_current_tenant_context)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    status_filter: Annotated[JobStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JobListResponse:
    require_api_key_scope(current_context, "jobs:read")
    jobs = await jobs_repository.list_tenant_jobs(
        db_session=db_session,
        tenant_id=current_context.tenant.id,
        status_filter=status_filter,
        limit=limit,
        offset=offset,
    )
    total = await jobs_repository.count_tenant_jobs(
        db_session=db_session,
        tenant_id=current_context.tenant.id,
        status_filter=status_filter,
    )
    return JobListResponse(
        items=[serialize_job(job) for job in jobs],
        total=total,
        limit=limit,
        offset=offset,
        has_more=offset + len(jobs) < total,
    )


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
    events = await jobs_repository.list_job_events(
        db_session=db_session,
        tenant_id=current_context.tenant.id,
        job_id=job_id,
    )
    return [serialize_event(event) for event in events]
