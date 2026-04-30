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

Start local Postgres from the repository root:

```bash
docker compose up -d postgres
```

The default connection string is:

```text
postgresql+asyncpg://reach:reach@127.0.0.1:5432/reach
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

## Test

```bash
uv run pytest
```
