import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import uuid

from fastapi import APIRouter, HTTPException, Query, WebSocket, status
from fastapi.websockets import WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1.dependencies import resolve_user_context
from app.api.v1.routes.jobs import serialize_event, serialize_job
from app.core.database import AsyncSessionLocal
from app.models import Job, JobEvent
from app.repositories import jobs as jobs_repository

router = APIRouter(prefix="/jobs", tags=["jobs"])

JOB_STREAM_POLL_INTERVAL_SECONDS = 0.5
JOB_STREAM_BATCH_SIZE = 100


@router.websocket("/stream")
async def stream_job_events(
    websocket: WebSocket,
    token: str | None = Query(default=None),
) -> None:
    if token is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    async with AsyncSessionLocal() as db_session:
        try:
            user_context = await resolve_user_context(
                token=token,
                db_session=db_session,
            )
        except HTTPException:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        except (SQLAlchemyError, OSError):
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
            return
        except Exception:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
            return

    tenant_id = user_context.tenant.id
    await websocket.accept()
    try:
        await websocket.send_json({"type": "connected"})
    except WebSocketDisconnect:
        return

    cursor = datetime.now(UTC) - timedelta(seconds=1)

    while True:
        try:
            cursor = await _send_pending_events(
                websocket=websocket,
                tenant_id=tenant_id,
                cursor=cursor,
            )
            try:
                message = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=JOB_STREAM_POLL_INTERVAL_SECONDS,
                )
            except TimeoutError:
                continue
            if message == "ping":
                await websocket.send_json({"type": "pong"})
        except WebSocketDisconnect:
            return


async def _send_pending_events(
    *,
    websocket: WebSocket,
    tenant_id: uuid.UUID,
    cursor: datetime,
) -> datetime:
    async with AsyncSessionLocal() as db_session:
        events = await _list_stream_events(
            db_session=db_session,
            tenant_id=tenant_id,
            cursor=cursor,
        )

    for event, job in events:
        await websocket.send_json(
            {
                "type": "job.event",
                "job": _dump_model(serialize_job(job)),
                "event": _dump_model(serialize_event(event)),
            }
        )
        cursor = max(cursor, event.created_at)

    return cursor


async def _list_stream_events(
    *,
    db_session: AsyncSession,
    tenant_id: uuid.UUID,
    cursor: datetime,
) -> list[tuple[JobEvent, Job]]:
    return await jobs_repository.list_tenant_job_events_after(
        db_session=db_session,
        tenant_id=tenant_id,
        after_created_at=cursor,
        limit=JOB_STREAM_BATCH_SIZE,
    )


def _dump_model(model) -> dict[str, Any]:
    return model.model_dump(mode="json", by_alias=True)
