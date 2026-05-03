from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import (
    AuthenticatedTenant,
    get_current_tenant_context,
    require_api_key_scope,
)
from app.core.database import get_db_session
from app.repositories.metrics import get_tenant_metrics_summary
from app.schemas import MetricsSummaryResponse

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/summary", response_model=MetricsSummaryResponse)
async def get_metrics_summary(
    current_context: Annotated[AuthenticatedTenant, Depends(get_current_tenant_context)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MetricsSummaryResponse:
    require_api_key_scope(current_context, "jobs:read")
    summary = await get_tenant_metrics_summary(
        db_session=db_session,
        tenant_id=current_context.tenant.id,
    )
    return MetricsSummaryResponse(
        pending=summary.pending,
        running=summary.running,
        succeeded=summary.succeeded,
        failed=summary.failed,
        dead_lettered=summary.dead_lettered,
        queue_depth=summary.queue_depth,
        oldest_pending_age_seconds=summary.oldest_pending_age_seconds,
        running_limit=summary.running_limit,
    )
