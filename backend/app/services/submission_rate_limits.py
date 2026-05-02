import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class SubmissionRateLimitResult:
    allowed: bool
    retry_after_seconds: int | None = None


async def reserve_submission_slot(
    *,
    db_session: AsyncSession,
    tenant_id: uuid.UUID,
) -> SubmissionRateLimitResult:
    result = await db_session.execute(
        text(
            """
            WITH attempted AS (
                INSERT INTO tenant_submission_rate_limits AS q (
                    tenant_id,
                    window_start,
                    submitted_count,
                    updated_at
                )
                SELECT t.id, date_trunc('minute', now()), 1, now()
                FROM tenants AS t
                WHERE t.id = :tenant_id
                ON CONFLICT (tenant_id) DO UPDATE
                SET window_start = CASE
                        WHEN q.window_start < date_trunc('minute', now())
                            THEN date_trunc('minute', now())
                        ELSE q.window_start
                    END,
                    submitted_count = CASE
                        WHEN q.window_start < date_trunc('minute', now()) THEN 1
                        ELSE q.submitted_count + 1
                    END,
                    updated_at = now()
                WHERE q.window_start < date_trunc('minute', now())
                   OR q.submitted_count < (
                        SELECT submit_rate_limit
                        FROM tenants
                        WHERE id = :tenant_id
                    )
                RETURNING tenant_id
            )
            SELECT tenant_id
            FROM attempted
            """
        ),
        {"tenant_id": tenant_id},
    )
    if result.first() is not None:
        return SubmissionRateLimitResult(allowed=True)

    retry_after_result = await db_session.execute(
        text(
            """
            SELECT GREATEST(
                1,
                CEIL(
                    EXTRACT(
                        EPOCH FROM (
                            q.window_start + interval '1 minute' - now()
                        )
                    )
                )::integer
            ) AS retry_after_seconds
            FROM tenant_submission_rate_limits AS q
            WHERE q.tenant_id = :tenant_id
            """
        ),
        {"tenant_id": tenant_id},
    )
    retry_after_seconds = retry_after_result.scalar_one_or_none()
    return SubmissionRateLimitResult(
        allowed=False,
        retry_after_seconds=retry_after_seconds or 60,
    )
