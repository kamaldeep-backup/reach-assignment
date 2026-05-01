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
from app.workers.handlers import (
    HandlerRegistry,
    NonRetryableJobError,
    RetryableJobError,
    build_default_registry,
)
from app.workers.settings import WorkerSettings, get_worker_settings

logger = logging.getLogger(__name__)


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

    logger.info(
        "job claimed",
        extra={
            "job_id": str(job.id),
            "tenant_id": str(job.tenant_id),
            "worker_id": worker_settings.worker_id,
            "attempt": job.attempts,
        },
    )

    try:
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
        logger.exception(
            "job handler raised unexpected error",
            extra={"job_id": str(job.id), "worker_id": worker_settings.worker_id},
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
                )
        if acknowledged:
            logger.info(
                "job succeeded",
                extra={"job_id": str(job.id), "worker_id": worker_settings.worker_id},
            )
        else:
            logger.warning(
                "job success acknowledgement was rejected",
                extra={"job_id": str(job.id), "worker_id": worker_settings.worker_id},
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
    logger.info("worker started", extra={"worker_id": worker_settings.worker_id})

    while not shutdown.is_set():
        job = await process_one_job(settings=worker_settings, registry=registry)
        if job is None:
            await asyncio.sleep(worker_settings.worker_poll_interval_seconds)

    logger.info("worker shutdown requested", extra={"worker_id": worker_settings.worker_id})


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
                error=error,
                backoff_seconds=backoff_seconds,
            )
    if scheduled:
        logger.info(
            "job retry scheduled",
            extra={
                "job_id": str(job.id),
                "worker_id": settings.worker_id,
                "backoff_seconds": backoff_seconds,
            },
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
                error=error,
            )
    if moved:
        logger.info("job dead-lettered", extra={"job_id": str(job.id)})


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
