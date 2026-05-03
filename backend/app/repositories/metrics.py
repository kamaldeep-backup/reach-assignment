import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DeadLetterJob, Job, JobStatus, Tenant, TenantRuntimeQuota


@dataclass(frozen=True)
class MetricsSummary:
    pending: int
    running: int
    succeeded: int
    failed: int
    dead_lettered: int
    queue_depth: int
    oldest_pending_age_seconds: int
    running_limit: int


@dataclass(frozen=True)
class TenantQueueMetrics:
    tenant_id: uuid.UUID
    counts: dict[JobStatus, int]
    dead_letter_jobs: int
    oldest_pending_age_seconds: int


@dataclass(frozen=True)
class MetricCounterTotal:
    metric_name: str
    labels: dict[str, str]
    value: int


async def get_tenant_metrics_summary(
    *,
    db_session: AsyncSession,
    tenant_id: uuid.UUID,
) -> MetricsSummary:
    counts = await _get_job_counts(db_session=db_session, tenant_id=tenant_id)
    oldest_pending_age_seconds = await _get_oldest_pending_age_seconds(
        db_session=db_session,
        tenant_id=tenant_id,
    )
    running_limit_result = await db_session.execute(
        select(Tenant.max_running_jobs).where(Tenant.id == tenant_id)
    )
    running_limit = int(running_limit_result.scalar_one())

    pending = counts[JobStatus.PENDING]
    return MetricsSummary(
        pending=pending,
        running=counts[JobStatus.RUNNING],
        succeeded=counts[JobStatus.SUCCEEDED],
        failed=counts[JobStatus.FAILED],
        dead_lettered=counts[JobStatus.DEAD_LETTERED],
        queue_depth=pending,
        oldest_pending_age_seconds=oldest_pending_age_seconds,
        running_limit=running_limit,
    )


async def list_all_tenant_queue_metrics(
    *,
    db_session: AsyncSession,
) -> list[TenantQueueMetrics]:
    tenant_result = await db_session.execute(select(Tenant.id).where(Tenant.is_active))
    tenant_ids = list(tenant_result.scalars().all())
    metrics_by_tenant = {
        tenant_id: TenantQueueMetrics(
            tenant_id=tenant_id,
            counts={status: 0 for status in JobStatus},
            dead_letter_jobs=0,
            oldest_pending_age_seconds=0,
        )
        for tenant_id in tenant_ids
    }

    job_count_result = await db_session.execute(
        select(Job.tenant_id, Job.status, func.count())
        .group_by(Job.tenant_id, Job.status)
        .order_by(Job.tenant_id)
    )
    for tenant_id, status, count in job_count_result.all():
        if tenant_id not in metrics_by_tenant:
            continue
        metrics_by_tenant[tenant_id].counts[status] = int(count)

    dead_letter_result = await db_session.execute(
        select(DeadLetterJob.tenant_id, func.count()).group_by(DeadLetterJob.tenant_id)
    )
    for tenant_id, count in dead_letter_result.all():
        if tenant_id not in metrics_by_tenant:
            continue
        current = metrics_by_tenant[tenant_id]
        metrics_by_tenant[tenant_id] = TenantQueueMetrics(
            tenant_id=current.tenant_id,
            counts=current.counts,
            dead_letter_jobs=int(count),
            oldest_pending_age_seconds=current.oldest_pending_age_seconds,
        )

    oldest_pending_result = await db_session.execute(
        select(Job.tenant_id, func.min(Job.created_at))
        .where(Job.status == JobStatus.PENDING)
        .group_by(Job.tenant_id)
    )
    now = datetime.now(UTC)
    for tenant_id, oldest_pending_at in oldest_pending_result.all():
        if tenant_id not in metrics_by_tenant or oldest_pending_at is None:
            continue
        current = metrics_by_tenant[tenant_id]
        metrics_by_tenant[tenant_id] = TenantQueueMetrics(
            tenant_id=current.tenant_id,
            counts=current.counts,
            dead_letter_jobs=current.dead_letter_jobs,
            oldest_pending_age_seconds=_age_seconds(now, oldest_pending_at),
        )

    return list(metrics_by_tenant.values())


async def list_tenant_running_limits(
    *,
    db_session: AsyncSession,
) -> list[tuple[uuid.UUID, int, int]]:
    result = await db_session.execute(
        select(
            Tenant.id,
            Tenant.max_running_jobs,
            func.coalesce(TenantRuntimeQuota.running_jobs, 0),
        ).outerjoin(TenantRuntimeQuota, TenantRuntimeQuota.tenant_id == Tenant.id)
    )
    return [
        (tenant_id, int(limit), int(running))
        for tenant_id, limit, running in result
    ]


async def list_lifecycle_counter_totals(
    *,
    db_session: AsyncSession,
) -> list[MetricCounterTotal]:
    result = await db_session.execute(
        text(
            """
            SELECT
                'jobs_submitted_total' AS metric_name,
                tenant_id::text AS tenant_id,
                NULL AS worker_id,
                count(*)::integer AS value
            FROM job_events
            WHERE event_type = 'SUBMITTED'
            GROUP BY tenant_id

            UNION ALL

            SELECT
                'jobs_claimed_total' AS metric_name,
                tenant_id::text AS tenant_id,
                COALESCE(metadata->>'workerId', 'unknown') AS worker_id,
                count(*)::integer AS value
            FROM job_events
            WHERE event_type = 'CLAIMED'
            GROUP BY tenant_id, COALESCE(metadata->>'workerId', 'unknown')

            UNION ALL

            SELECT
                'jobs_succeeded_total' AS metric_name,
                tenant_id::text AS tenant_id,
                COALESCE(metadata->>'workerId', 'unknown') AS worker_id,
                count(*)::integer AS value
            FROM job_events
            WHERE event_type = 'SUCCEEDED'
            GROUP BY tenant_id, COALESCE(metadata->>'workerId', 'unknown')

            UNION ALL

            SELECT
                'jobs_retried_total' AS metric_name,
                tenant_id::text AS tenant_id,
                NULL AS worker_id,
                count(*)::integer AS value
            FROM job_events
            WHERE event_type = 'FAILED_RETRY_SCHEDULED'
            GROUP BY tenant_id

            UNION ALL

            SELECT
                'jobs_dead_lettered_total' AS metric_name,
                tenant_id::text AS tenant_id,
                NULL AS worker_id,
                count(*)::integer AS value
            FROM job_events
            WHERE event_type = 'DEAD_LETTERED'
            GROUP BY tenant_id

            UNION ALL

            SELECT
                'job_lease_expired_total' AS metric_name,
                tenant_id::text AS tenant_id,
                NULL AS worker_id,
                count(*)::integer AS value
            FROM job_events
            WHERE event_type = 'LEASE_EXPIRED'
            GROUP BY tenant_id
            """
        )
    )

    totals: list[MetricCounterTotal] = []
    for row in result.mappings().all():
        labels = {"tenant_id": row["tenant_id"]}
        if row["worker_id"] is not None:
            labels["worker_id"] = row["worker_id"]
        totals.append(
            MetricCounterTotal(
                metric_name=row["metric_name"],
                labels=labels,
                value=int(row["value"]),
            )
        )
    return totals


async def _get_job_counts(
    *,
    db_session: AsyncSession,
    tenant_id: uuid.UUID,
) -> dict[JobStatus, int]:
    counts = {status: 0 for status in JobStatus}
    result = await db_session.execute(
        select(Job.status, func.count())
        .where(Job.tenant_id == tenant_id)
        .group_by(Job.status)
    )
    for status, count in result.all():
        counts[status] = int(count)
    return counts


async def _get_oldest_pending_age_seconds(
    *,
    db_session: AsyncSession,
    tenant_id: uuid.UUID,
) -> int:
    result = await db_session.execute(
        select(func.min(Job.created_at)).where(
            Job.tenant_id == tenant_id,
            Job.status == JobStatus.PENDING,
        )
    )
    oldest_pending_at = result.scalar_one_or_none()
    if oldest_pending_at is None:
        return 0
    return _age_seconds(datetime.now(UTC), oldest_pending_at)


def _age_seconds(now: datetime, value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return max(0, int((now - value).total_seconds()))
