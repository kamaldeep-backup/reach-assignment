import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.api.v1.routes import job_stream
from app.api.v1.routes.job_stream import (
    JobEventCursor,
    MIN_JOB_EVENT_ID,
    _send_pending_events,
    stream_job_events,
)
from app.core.database import AsyncSessionLocal, dispose_database_engine
from app.models import (
    APIKey,
    DeadLetterJob,
    Job,
    JobEvent,
    JobStatus,
    Tenant,
    TenantRuntimeQuota,
    TenantSubmissionRateLimit,
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
            TenantSubmissionRateLimit,
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
        cursor=JobEventCursor(
            created_at=event.created_at.replace(year=event.created_at.year - 1),
            event_id=MIN_JOB_EVENT_ID,
        ),
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


@pytest.mark.anyio
async def test_job_stream_cursor_keeps_same_timestamp_events_across_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(job_stream, "JOB_STREAM_BATCH_SIZE", 1)
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    first_event_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    second_event_id = uuid.UUID("00000000-0000-0000-0000-000000000002")

    async with AsyncSessionLocal() as session:
        tenant = Tenant(name="Acme")
        session.add(tenant)
        await session.flush()
        job = Job(
            tenant_id=tenant.id,
            idempotency_key="same-timestamp-job",
            job_type="noop",
            payload={"ok": True},
        )
        session.add(job)
        await session.flush()
        session.add_all(
            [
                JobEvent(
                    id=first_event_id,
                    job_id=job.id,
                    tenant_id=tenant.id,
                    event_type="FIRST",
                    from_status=None,
                    to_status=JobStatus.PENDING,
                    created_at=created_at,
                ),
                JobEvent(
                    id=second_event_id,
                    job_id=job.id,
                    tenant_id=tenant.id,
                    event_type="SECOND",
                    from_status=None,
                    to_status=JobStatus.PENDING,
                    created_at=created_at,
                ),
            ]
        )
        await session.commit()
        await session.refresh(tenant)

    websocket = FakeWebSocket()
    cursor = JobEventCursor(
        created_at=created_at - timedelta(microseconds=1),
        event_id=MIN_JOB_EVENT_ID,
    )

    cursor = await _send_pending_events(
        websocket=websocket,
        tenant_id=tenant.id,
        cursor=cursor,
    )
    cursor = await _send_pending_events(
        websocket=websocket,
        tenant_id=tenant.id,
        cursor=cursor,
    )

    assert [message["event"]["eventId"] for message in websocket.messages] == [
        str(first_event_id),
        str(second_event_id),
    ]
    assert cursor == JobEventCursor(created_at=created_at, event_id=second_event_id)


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages = []
        self.close_code = None

    async def send_json(self, payload) -> None:
        self.messages.append(payload)

    async def close(self, code: int) -> None:
        self.close_code = code
