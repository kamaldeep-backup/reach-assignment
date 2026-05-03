import asyncio
import logging
import signal

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.core.database import AsyncSessionLocal
from app.observability.tracing import log_event, trace_span
from app.repositories.worker_jobs import LeaseRecoveryResult, recover_expired_leases
from app.workers.settings import WorkerSettings, get_worker_settings
from app.workers.worker import calculate_backoff_seconds


async def recover_once(
    *,
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
    settings: WorkerSettings | None = None,
) -> list[LeaseRecoveryResult]:
    worker_settings = settings or get_worker_settings()

    def backoff_seconds_for_attempt(attempts: int) -> float:
        return calculate_backoff_seconds(
            attempts=attempts,
            base_seconds=worker_settings.worker_base_backoff_seconds,
            max_seconds=worker_settings.worker_max_backoff_seconds,
            jitter_seconds=worker_settings.worker_jitter_seconds,
        )

    with trace_span(
        "lease_reaper.recover_expired_leases",
        batchSize=worker_settings.lease_reaper_batch_size,
    ):
        async with session_factory() as session:
            async with session.begin():
                recovered = await recover_expired_leases(
                    db_session=session,
                    batch_size=worker_settings.lease_reaper_batch_size,
                    backoff_seconds_for_attempt=backoff_seconds_for_attempt,
                )

    for result in recovered:
        log_event(
            "lease_reaper.expired_lease_recovered",
            jobId=result.job_id,
            status=result.status.value,
        )
    return recovered


async def run_reaper(
    *,
    settings: WorkerSettings | None = None,
    stop_event: asyncio.Event | None = None,
) -> None:
    worker_settings = settings or get_worker_settings()
    shutdown = stop_event or asyncio.Event()
    _install_signal_handlers(shutdown)
    logging.basicConfig(level=logging.INFO)
    log_event("lease_reaper.started")

    while not shutdown.is_set():
        await recover_once(settings=worker_settings)
        await asyncio.sleep(worker_settings.lease_reaper_interval_seconds)

    log_event("lease_reaper.shutdown_requested")


def _install_signal_handlers(shutdown: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_args: shutdown.set())


def main() -> None:
    asyncio.run(run_reaper())


if __name__ == "__main__":
    main()
