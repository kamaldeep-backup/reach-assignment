# Reach Backend

Minimal FastAPI backend scaffold.

## Setup

```bash
uv venv
source .venv/bin/activate
uv sync --dev
cp .env.example .env
```

## Database

Start the backend and local Postgres from the repository root:

```bash
docker compose up
```

The default local connection string for running the backend outside Docker is:

```text
postgresql+asyncpg://reach:reach@127.0.0.1:5432/reach
```

When running through Docker Compose, the server loads variables from
`backend/.env` when present and overrides `DATABASE_URL` to use the Compose
Postgres service hostname:

```text
postgresql+asyncpg://reach:reach@postgres:5432/reach
```

## Run locally

```bash
uv run uvicorn app.main:app --reload
```

Or, with the virtualenv activated:

```bash
uvicorn app.main:app --reload
```

## Health check

```bash
curl http://127.0.0.1:8000/api/v1/health
curl http://127.0.0.1:8000/api/v1/health/database
```

## Observability

HTTP middleware accepts or generates `X-Request-ID` and `X-Trace-ID`, returns
both response headers, and emits structured JSON request logs. Job submission
stores those IDs in `job_events.metadata`; worker and lease-reaper events
propagate them when available.

Prometheus-compatible metrics are exposed without application auth for scrapers:

```bash
curl http://127.0.0.1:8000/metrics
```

The authenticated dashboard uses database-backed operational counts instead of
sampling job rows:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/api/v1/metrics/summary
```

## Test

```bash
uv run pytest
```
