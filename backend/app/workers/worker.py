import asyncio
from collections.abc import Callable
import logging
import random
import signal

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.core.database import AsyncSessionLocal
from app.repositories.worker_jobs import (
    ClaimedJob,
    claim_pending_job,
    mark_job_succeeded,
    move_owned_job_to_dlq,
    schedule_job_retry,
)
from app.observability.tracing import log_event, observability_context, trace_span
from app.workers.handlers import (
    HandlerRegistry,
    NonRetryableJobError,
    RetryableJobError,
    build_default_registry,
)
from app.workers.settings import WorkerSettings, get_worker_settings


def calculate_backoff_seconds(
    *,
    attempts: int,
    base_seconds: float,
    max_seconds: float,
    jitter_seconds: float,
    random_fn: Callable[[float, float], float] = random.uniform,
) -> float:
    exponential_delay = base_seconds * (2 ** max(attempts - 1, 0))
    jitter = random_fn(0, jitter_seconds) if jitter_seconds > 0 else 0
    return min(max_seconds, exponential_delay + jitter)


async def process_one_job(
    *,
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
    settings: WorkerSettings | None = None,
    registry: HandlerRegistry | None = None,
) -> ClaimedJob | None:
    worker_settings = settings or get_worker_settings()
    handler_registry = registry or build_default_registry()

    async with session_factory() as session:
        async with session.begin():
            job = await claim_pending_job(
                db_session=session,
                worker_id=worker_settings.worker_id,
                lease_seconds=worker_settings.worker_lease_seconds,
                candidate_limit=worker_settings.worker_batch_size,
            )

    if job is None:
        return None

    with observability_context(request_id=job.request_id, trace_id=job.trace_id):
        log_event(
            "worker.job.claimed",
            jobId=job.id,
            tenantId=job.tenant_id,
            workerId=worker_settings.worker_id,
            leaseId=job.lease_id,
            attempt=job.attempts,
        )
        try:
            with trace_span(
                "worker.job.execute",
                jobId=job.id,
                tenantId=job.tenant_id,
                workerId=worker_settings.worker_id,
                leaseId=job.lease_id,
                jobType=job.job_type,
                attempt=job.attempts,
            ):
                await handler_registry.execute(job)
        except NonRetryableJobError as exc:
            await _dead_letter(
                session_factory=session_factory,
                job=job,
                worker_id=worker_settings.worker_id,
                error=str(exc),
            )
        except RetryableJobError as exc:
            await _retry_or_dead_letter(
                session_factory=session_factory,
                settings=worker_settings,
                job=job,
                error=str(exc),
            )
        except Exception as exc:
            log_event(
                "worker.job.handler_unexpected_error",
                level=logging.ERROR,
                jobId=job.id,
                workerId=worker_settings.worker_id,
                leaseId=job.lease_id,
                errorType=type(exc).__name__,
                error=str(exc),
            )
            await _retry_or_dead_letter(
                session_factory=session_factory,
                settings=worker_settings,
                job=job,
                error=f"{type(exc).__name__}: {exc}",
            )
        else:
            async with session_factory() as session:
                async with session.begin():
                    acknowledged = await mark_job_succeeded(
                        db_session=session,
                        job_id=job.id,
                        worker_id=worker_settings.worker_id,
                        lease_id=job.lease_id,
                    )
            if acknowledged:
                log_event(
                    "worker.job.succeeded",
                    jobId=job.id,
                    workerId=worker_settings.worker_id,
                    leaseId=job.lease_id,
                )
            else:
                log_event(
                    "worker.job.success_ack_rejected",
                    level=logging.WARNING,
                    jobId=job.id,
                    workerId=worker_settings.worker_id,
                    leaseId=job.lease_id,
                )

    return job


async def run_worker(
    *,
    settings: WorkerSettings | None = None,
    registry: HandlerRegistry | None = None,
    stop_event: asyncio.Event | None = None,
) -> None:
    worker_settings = settings or get_worker_settings()
    shutdown = stop_event or asyncio.Event()
    _install_signal_handlers(shutdown)
    logging.basicConfig(level=logging.INFO)
    log_event("worker.started", workerId=worker_settings.worker_id)

    while not shutdown.is_set():
        job = await process_one_job(settings=worker_settings, registry=registry)
        if job is None:
            await asyncio.sleep(worker_settings.worker_poll_interval_seconds)

    log_event("worker.shutdown_requested", workerId=worker_settings.worker_id)


async def _retry_or_dead_letter(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    settings: WorkerSettings,
    job: ClaimedJob,
    error: str,
) -> None:
    if job.attempts >= job.max_attempts:
        await _dead_letter(
            session_factory=session_factory,
            job=job,
            worker_id=settings.worker_id,
            error=error,
        )
        return

    backoff_seconds = calculate_backoff_seconds(
        attempts=job.attempts,
        base_seconds=settings.worker_base_backoff_seconds,
        max_seconds=settings.worker_max_backoff_seconds,
        jitter_seconds=settings.worker_jitter_seconds,
    )
    async with session_factory() as session:
        async with session.begin():
            scheduled = await schedule_job_retry(
                db_session=session,
                job_id=job.id,
                worker_id=settings.worker_id,
                lease_id=job.lease_id,
                error=error,
                backoff_seconds=backoff_seconds,
            )
    if scheduled:
        log_event(
            "worker.job.retry_scheduled",
            jobId=job.id,
            workerId=settings.worker_id,
            leaseId=job.lease_id,
            backoffSeconds=backoff_seconds,
        )


async def _dead_letter(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    job: ClaimedJob,
    worker_id: str,
    error: str,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            moved = await move_owned_job_to_dlq(
                db_session=session,
                job_id=job.id,
                worker_id=worker_id,
                lease_id=job.lease_id,
                error=error,
            )
    if moved:
        log_event(
            "worker.job.dead_lettered",
            jobId=job.id,
            workerId=worker_id,
            leaseId=job.lease_id,
        )


def _install_signal_handlers(shutdown: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_args: shutdown.set())


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
