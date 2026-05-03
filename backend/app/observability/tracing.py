from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
import json
import logging
import time
import uuid
from typing import Any

from fastapi import FastAPI, Request

REQUEST_ID_HEADER = "X-Request-ID"
TRACE_ID_HEADER = "X-Trace-ID"

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)
_span_id: ContextVar[str | None] = ContextVar("span_id", default=None)

logger = logging.getLogger("app.observability")
logger.setLevel(logging.INFO)


def generate_correlation_id() -> str:
    return uuid.uuid4().hex


def get_request_id() -> str | None:
    return _request_id.get()


def get_trace_id() -> str | None:
    return _trace_id.get()


def current_trace_metadata() -> dict[str, str]:
    metadata: dict[str, str] = {}
    request_id = get_request_id()
    trace_id = get_trace_id()
    if request_id is not None:
        metadata["requestId"] = request_id
    if trace_id is not None:
        metadata["traceId"] = trace_id
    return metadata


@contextmanager
def observability_context(
    *,
    request_id: str | None = None,
    trace_id: str | None = None,
) -> Iterator[None]:
    request_token = _request_id.set(request_id)
    trace_token = _trace_id.set(trace_id or generate_correlation_id())
    span_token = _span_id.set(None)
    try:
        yield
    finally:
        _span_id.reset(span_token)
        _trace_id.reset(trace_token)
        _request_id.reset(request_token)


@contextmanager
def trace_span(name: str, **fields: Any) -> Iterator[str]:
    trace_id = get_trace_id()
    if trace_id is None:
        with observability_context():
            with trace_span(name, **fields) as nested_span_id:
                yield nested_span_id
        return

    parent_span_id = _span_id.get()
    span_id = uuid.uuid4().hex[:16]
    span_token = _span_id.set(span_id)
    started_at = time.perf_counter()
    log_event(
        "trace.span.start",
        spanName=name,
        spanId=span_id,
        parentSpanId=parent_span_id,
        **fields,
    )
    try:
        yield span_id
    except Exception as exc:
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        log_event(
            "trace.span.end",
            level=logging.ERROR,
            spanName=name,
            spanId=span_id,
            parentSpanId=parent_span_id,
            durationMs=duration_ms,
            outcome="error",
            errorType=type(exc).__name__,
            **fields,
        )
        raise
    else:
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        log_event(
            "trace.span.end",
            spanName=name,
            spanId=span_id,
            parentSpanId=parent_span_id,
            durationMs=duration_ms,
            outcome="ok",
            **fields,
        )
    finally:
        _span_id.reset(span_token)


def log_event(event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    payload = {
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "level": logging.getLevelName(level),
        "event": event,
    }
    request_id = get_request_id()
    trace_id = get_trace_id()
    span_id = _span_id.get()
    if request_id is not None:
        payload["requestId"] = request_id
    if trace_id is not None:
        payload["traceId"] = trace_id
    if span_id is not None:
        payload["spanId"] = span_id
    payload.update({key: value for key, value in fields.items() if value is not None})
    logger.log(level, json.dumps(payload, default=str, separators=(",", ":")))


def install_observability_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def observability_middleware(request: Request, call_next):
        request_id = (
            request.headers.get(REQUEST_ID_HEADER)
            or request.headers.get(REQUEST_ID_HEADER.lower())
            or generate_correlation_id()
        )
        trace_id = (
            request.headers.get(TRACE_ID_HEADER)
            or request.headers.get(TRACE_ID_HEADER.lower())
            or generate_correlation_id()
        )

        with observability_context(request_id=request_id, trace_id=trace_id):
            started_at = time.perf_counter()
            log_event(
                "http.request.start",
                method=request.method,
                path=request.url.path,
                clientHost=request.client.host if request.client else None,
            )
            try:
                response = await call_next(request)
            except Exception as exc:
                duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
                log_event(
                    "http.request.error",
                    level=logging.ERROR,
                    method=request.method,
                    path=request.url.path,
                    durationMs=duration_ms,
                    errorType=type(exc).__name__,
                )
                raise

            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            response.headers[REQUEST_ID_HEADER] = request_id
            response.headers[TRACE_ID_HEADER] = trace_id
            log_event(
                "http.request.finish",
                method=request.method,
                path=request.url.path,
                statusCode=response.status_code,
                durationMs=duration_ms,
            )
            return response
