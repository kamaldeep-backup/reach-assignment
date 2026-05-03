import uuid
from datetime import UTC, datetime

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import JobStatus
from app.repositories.metrics import (
    MetricCounterTotal,
    list_all_tenant_queue_metrics,
    list_lifecycle_counter_totals,
    list_tenant_running_limits,
)

JOBS_SUBMITTED = Counter(
    "jobs_submitted_total",
    "Jobs accepted for asynchronous execution.",
    ("tenant_id",),
)
JOBS_CLAIMED = Counter(
    "jobs_claimed_total",
    "Jobs claimed by workers.",
    ("tenant_id", "worker_id"),
)
JOBS_SUCCEEDED = Counter(
    "jobs_succeeded_total",
    "Jobs acknowledged as successfully completed.",
    ("tenant_id", "worker_id"),
)
JOBS_RETRIED = Counter(
    "jobs_retried_total",
    "Jobs requeued for a retry after a worker failure.",
    ("tenant_id",),
)
JOBS_DEAD_LETTERED = Counter(
    "jobs_dead_lettered_total",
    "Jobs moved to the dead letter queue.",
    ("tenant_id",),
)
JOB_LEASE_EXPIRED = Counter(
    "job_lease_expired_total",
    "Running job leases recovered after expiration.",
    ("tenant_id",),
)
TENANT_RATE_LIMITED = Counter(
    "tenant_rate_limited_total",
    "Job submissions rejected by tenant rate limiting.",
    ("tenant_id",),
)

QUEUE_DEPTH = Gauge(
    "queue_depth",
    "Current database-backed job counts by tenant and status.",
    ("tenant_id", "status"),
)
RUNNING_JOBS = Gauge(
    "running_jobs",
    "Current database-backed running jobs by tenant.",
    ("tenant_id",),
)
DEAD_LETTER_JOBS = Gauge(
    "dead_letter_jobs",
    "Current database-backed dead letter jobs by tenant.",
    ("tenant_id",),
)
OLDEST_PENDING_AGE_SECONDS = Gauge(
    "oldest_pending_age_seconds",
    "Age in seconds of the oldest pending job by tenant.",
    ("tenant_id",),
)
TENANT_RUNNING_LIMIT = Gauge(
    "tenant_running_limit",
    "Configured maximum running jobs by tenant.",
    ("tenant_id",),
)
TENANT_RUNTIME_SLOTS_USED = Gauge(
    "tenant_runtime_slots_used",
    "Runtime quota slots currently reserved by tenant.",
    ("tenant_id",),
)

JOB_EXECUTION_DURATION = Histogram(
    "job_execution_duration_seconds",
    "Seconds between worker claim and terminal or retry acknowledgement.",
    ("tenant_id", "job_type", "outcome"),
)
JOB_QUEUE_WAIT = Histogram(
    "job_queue_wait_seconds",
    "Seconds between job creation and worker claim.",
    ("tenant_id", "job_type"),
)

_LIFECYCLE_COUNTERS = {
    "jobs_submitted_total": JOBS_SUBMITTED,
    "jobs_claimed_total": JOBS_CLAIMED,
    "jobs_succeeded_total": JOBS_SUCCEEDED,
    "jobs_retried_total": JOBS_RETRIED,
    "jobs_dead_lettered_total": JOBS_DEAD_LETTERED,
    "job_lease_expired_total": JOB_LEASE_EXPIRED,
}
_COUNTER_SNAPSHOTS: dict[tuple[str, tuple[tuple[str, str], ...]], int] = {}


def record_job_submitted(tenant_id: uuid.UUID) -> None:
    _increment_counter(
        metric_name="jobs_submitted_total",
        labels={"tenant_id": str(tenant_id)},
    )


def record_job_claimed(
    *,
    tenant_id: uuid.UUID,
    worker_id: str,
    job_type: str,
    created_at: datetime,
    claimed_at: datetime,
) -> None:
    _increment_counter(
        metric_name="jobs_claimed_total",
        labels={"tenant_id": str(tenant_id), "worker_id": worker_id},
    )
    JOB_QUEUE_WAIT.labels(
        tenant_id=str(tenant_id),
        job_type=job_type,
    ).observe(_duration_seconds(created_at, claimed_at))


def record_job_succeeded(
    *,
    tenant_id: uuid.UUID,
    worker_id: str,
    job_type: str,
    claimed_at: datetime,
    completed_at: datetime,
) -> None:
    _increment_counter(
        metric_name="jobs_succeeded_total",
        labels={"tenant_id": str(tenant_id), "worker_id": worker_id},
    )
    _observe_execution_duration(
        tenant_id=tenant_id,
        job_type=job_type,
        outcome="succeeded",
        claimed_at=claimed_at,
        finished_at=completed_at,
    )


def record_job_retried(
    *,
    tenant_id: uuid.UUID,
    job_type: str,
    claimed_at: datetime,
    finished_at: datetime,
) -> None:
    _increment_counter(
        metric_name="jobs_retried_total",
        labels={"tenant_id": str(tenant_id)},
    )
    _observe_execution_duration(
        tenant_id=tenant_id,
        job_type=job_type,
        outcome="retried",
        claimed_at=claimed_at,
        finished_at=finished_at,
    )


def record_job_dead_lettered(
    *,
    tenant_id: uuid.UUID,
    job_type: str,
    claimed_at: datetime | None,
    finished_at: datetime,
) -> None:
    _increment_counter(
        metric_name="jobs_dead_lettered_total",
        labels={"tenant_id": str(tenant_id)},
    )
    if claimed_at is not None:
        _observe_execution_duration(
            tenant_id=tenant_id,
            job_type=job_type,
            outcome="dead_lettered",
            claimed_at=claimed_at,
            finished_at=finished_at,
        )


def record_job_lease_expired(tenant_id: uuid.UUID) -> None:
    _increment_counter(
        metric_name="job_lease_expired_total",
        labels={"tenant_id": str(tenant_id)},
    )


def record_tenant_rate_limited(tenant_id: uuid.UUID) -> None:
    TENANT_RATE_LIMITED.labels(tenant_id=str(tenant_id)).inc()


async def refresh_database_gauges(db_session: AsyncSession) -> None:
    await _sync_lifecycle_counters(db_session)

    for tenant_metrics in await list_all_tenant_queue_metrics(db_session=db_session):
        tenant_id = str(tenant_metrics.tenant_id)
        for status in JobStatus:
            QUEUE_DEPTH.labels(tenant_id=tenant_id, status=status.value).set(
                tenant_metrics.counts[status]
            )
        RUNNING_JOBS.labels(tenant_id=tenant_id).set(
            tenant_metrics.counts[JobStatus.RUNNING]
        )
        DEAD_LETTER_JOBS.labels(tenant_id=tenant_id).set(
            tenant_metrics.dead_letter_jobs
        )
        OLDEST_PENDING_AGE_SECONDS.labels(tenant_id=tenant_id).set(
            tenant_metrics.oldest_pending_age_seconds
        )

    for tenant_id, running_limit, runtime_slots_used in await list_tenant_running_limits(
        db_session=db_session
    ):
        tenant_id_label = str(tenant_id)
        TENANT_RUNNING_LIMIT.labels(tenant_id=tenant_id_label).set(running_limit)
        TENANT_RUNTIME_SLOTS_USED.labels(tenant_id=tenant_id_label).set(
            runtime_slots_used
        )


def render_prometheus_metrics() -> bytes:
    return generate_latest()


def prometheus_content_type() -> str:
    return CONTENT_TYPE_LATEST


async def _sync_lifecycle_counters(db_session: AsyncSession) -> None:
    for total in await list_lifecycle_counter_totals(db_session=db_session):
        _sync_counter(total)


def _sync_counter(total: MetricCounterTotal) -> None:
    key = _counter_key(total.metric_name, total.labels)
    previous_value = _COUNTER_SNAPSHOTS.get(key, 0)
    if total.value <= previous_value:
        return

    _increment_counter(
        metric_name=total.metric_name,
        labels=total.labels,
        amount=total.value - previous_value,
    )


def _increment_counter(
    *,
    metric_name: str,
    labels: dict[str, str],
    amount: int = 1,
) -> None:
    _LIFECYCLE_COUNTERS[metric_name].labels(**labels).inc(amount)
    key = _counter_key(metric_name, labels)
    _COUNTER_SNAPSHOTS[key] = _COUNTER_SNAPSHOTS.get(key, 0) + amount


def _counter_key(
    metric_name: str,
    labels: dict[str, str],
) -> tuple[str, tuple[tuple[str, str], ...]]:
    return metric_name, tuple(sorted(labels.items()))


def _observe_execution_duration(
    *,
    tenant_id: uuid.UUID,
    job_type: str,
    outcome: str,
    claimed_at: datetime,
    finished_at: datetime,
) -> None:
    JOB_EXECUTION_DURATION.labels(
        tenant_id=str(tenant_id),
        job_type=job_type,
        outcome=outcome,
    ).observe(_duration_seconds(claimed_at, finished_at))


def _duration_seconds(start: datetime, end: datetime) -> float:
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    return max(0.0, (end - start).total_seconds())
