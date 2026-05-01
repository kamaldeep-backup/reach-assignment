import pytest
from sqlalchemy import delete

from app.api.v1.routes.job_stream import _send_pending_events, stream_job_events
from app.core.database import AsyncSessionLocal, dispose_database_engine
from app.models import (
    APIKey,
    DeadLetterJob,
    Job,
    JobEvent,
    JobStatus,
    Tenant,
    TenantRuntimeQuota,
    TenantUser,
    User,
)


@pytest.fixture(autouse=True)
async def clean_stream_tables() -> None:
    await _clean_tables()
    yield
    await _clean_tables()
    await dispose_database_engine()


async def _clean_tables() -> None:
    await dispose_database_engine()
    async with AsyncSessionLocal() as session:
        for model in (
            DeadLetterJob,
            JobEvent,
            Job,
            TenantRuntimeQuota,
            APIKey,
            TenantUser,
            User,
            Tenant,
        ):
            await session.execute(delete(model))
        await session.commit()


@pytest.mark.anyio
async def test_job_stream_rejects_missing_token() -> None:
    websocket = FakeWebSocket()

    await stream_job_events(websocket=websocket, token=None)

    assert websocket.close_code == 1008


@pytest.mark.anyio
async def test_job_stream_pushes_job_events_for_tenant() -> None:
    async with AsyncSessionLocal() as session:
        tenant = Tenant(name="Acme")
        session.add(tenant)
        await session.flush()
        job = Job(
            tenant_id=tenant.id,
            idempotency_key="streamed-job",
            job_type="noop",
            payload={"ok": True},
        )
        session.add(job)
        await session.flush()
        event = JobEvent(
            job_id=job.id,
            tenant_id=tenant.id,
            event_type="SUBMITTED",
            from_status=None,
            to_status=JobStatus.PENDING,
            message="Job submitted",
        )
        session.add(event)
        await session.commit()
        await session.refresh(tenant)
        await session.refresh(job)
        await session.refresh(event)

    websocket = FakeWebSocket()
    await _send_pending_events(
        websocket=websocket,
        tenant_id=tenant.id,
        cursor=event.created_at.replace(year=event.created_at.year - 1),
    )

    assert len(websocket.messages) == 1
    message = websocket.messages[0]
    assert message["type"] == "job.event"
    assert message["job"]["jobId"] == str(job.id)
    assert message["job"]["idempotencyKey"] == "streamed-job"
    assert message["job"]["status"] == "PENDING"
    assert message["job"]["attempts"] == 0
    assert message["event"]["eventId"] == str(event.id)
    assert message["event"]["jobId"] == str(job.id)
    assert message["event"]["eventType"] == "SUBMITTED"
    assert message["event"]["toStatus"] == "PENDING"


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages = []
        self.close_code = None

    async def send_json(self, payload) -> None:
        self.messages.append(payload)

    async def close(self, code: int) -> None:
        self.close_code = code
