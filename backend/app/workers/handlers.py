import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.repositories.worker_jobs import ClaimedJob

logger = logging.getLogger(__name__)


class RetryableJobError(Exception):
    """Raised when a job can be retried after backoff."""


class NonRetryableJobError(Exception):
    """Raised when retrying cannot make a job succeed."""


JobHandler = Callable[[ClaimedJob], Awaitable[None]]


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}

    def register(self, job_type: str, handler: JobHandler) -> None:
        self._handlers[job_type] = handler

    async def execute(self, job: ClaimedJob) -> None:
        handler = self._handlers.get(job.job_type)
        if handler is None:
            raise NonRetryableJobError(f"Unknown job type: {job.job_type}")
        await handler(job)


async def noop_handler(job: ClaimedJob) -> None:
    return None


async def send_email_handler(job: ClaimedJob) -> None:
    if "to" not in job.payload:
        raise NonRetryableJobError("send_email payload requires 'to'")
    logger.info(
        "send_email job completed",
        extra={"job_id": str(job.id), "tenant_id": str(job.tenant_id)},
    )


async def webhook_handler(job: ClaimedJob) -> None:
    if "url" not in job.payload:
        raise NonRetryableJobError("webhook payload requires 'url'")
    logger.info(
        "webhook job completed",
        extra={"job_id": str(job.id), "tenant_id": str(job.tenant_id)},
    )


async def fail_once_handler(job: ClaimedJob) -> None:
    if job.attempts == 1:
        raise RetryableJobError("Intentional first-attempt failure")
    await asyncio.sleep(0)


def build_default_registry() -> HandlerRegistry:
    registry = HandlerRegistry()
    registry.register("noop", noop_handler)
    registry.register("send_email", send_email_handler)
    registry.register("webhook", webhook_handler)
    registry.register("fail_once", fail_once_handler)
    return registry
