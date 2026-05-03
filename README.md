# Reach Assignment

Distributed task queue and job-processing platform built as a take-home
assignment. The repo contains a FastAPI backend, a Postgres-backed durable job
queue, raw Python worker processes, a lease reaper, Prometheus metrics,
structured JSON logs with request/trace IDs, and a React/Vite dashboard for
authentication, job submission, job monitoring, and API key management.

## Repository Overview

The system accepts authenticated JSON jobs, stores them durably in Postgres, and
executes them asynchronously through worker processes. Jobs use tenant-scoped
idempotency keys, rate limits, runtime concurrency quotas, retry/backoff
behavior, explicit worker leases, and a dead-letter state for exhausted failures.

```text
.
|-- docker-compose.yml          # Local full-stack runtime
|-- docs/
|   |-- ARCHITECTURE.md         # End-to-end distributed queue design
|   |-- CRUD_SERVER.md          # Baseline API server design
|   `-- WORKERS.md              # Worker, lease, retry, and DLQ design
|-- backend/
|   |-- README.md               # Backend-specific setup and commands
|   |-- .env.example            # Backend environment template
|   |-- app/                    # FastAPI app, routes, models, services, workers
|   |-- migrations/             # Alembic migrations
|   `-- tests/                  # Pytest backend test suite
`-- frontend/
    |-- README.md               # Frontend-specific setup and conventions
    |-- package.json            # Vite/React scripts
    `-- src/                    # Dashboard application code
```

At a high level:

- `backend/app/api/v1/routes/` exposes auth, API key, job, job stream, health,
  and metrics endpoints.
- `backend/app/repositories/` owns database access for users, API keys, jobs,
  worker claims, and metrics.
- `backend/app/workers/` contains the worker loop, demo job handlers, worker
  settings, and lease reaper.
- `frontend/src/features/` contains the auth and dashboard experiences.
- `frontend/src/lib/` contains API clients, query setup, and shared utilities.

## Prerequisites

For the Docker path:

- Docker and Docker Compose

For local development outside containers:

- Python 3.11+
- `uv`
- Node.js 24 or another recent Node version with Corepack enabled
- `pnpm@10.15.1`

## Quick Start With Docker Compose

1. Create the backend environment file:

```bash
cp backend/.env.example backend/.env
```

2. Set a real `SECRET_KEY` in `backend/.env`:

```bash
openssl rand -hex 32
```

3. Start the full stack from the repository root:

```bash
docker compose up --build
```

Compose starts:

- `postgres` on `POSTGRES_PORT` or `5432`
- `server` on `SERVER_PORT` or `8000`
- `worker`
- `lease-reaper`
- `frontend` on `FRONTEND_PORT` or `5173`

Open the dashboard at:

```text
http://localhost:5173
```

The API is available at:

```text
http://127.0.0.1:8000
```

Useful backend URLs:

- `http://127.0.0.1:8000/docs` for FastAPI Swagger docs
- `http://127.0.0.1:8000/api/v1/health` for the API health check
- `http://127.0.0.1:8000/api/v1/health/database` for database health
- `http://127.0.0.1:8000/metrics` for Prometheus-compatible metrics

## Local Backend Development

Start Postgres from the repository root:

```bash
docker compose up postgres
```

In another shell, install and run the backend:

```bash
cd backend
uv sync --dev
cp .env.example .env
```

Set `SECRET_KEY` in `backend/.env`, then run migrations and start FastAPI:

```bash
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Optional worker processes can be run from `backend/` in separate shells:

```bash
uv run python -m app.workers.worker
uv run python -m app.workers.lease_reaper
```

Backend tests:

```bash
cd backend
uv run pytest
```

More backend detail is in [backend/README.md](backend/README.md).

## Local Frontend Development

Start the backend first, then install and run the dashboard:

```bash
cd frontend
corepack enable
corepack prepare pnpm@10.15.1 --activate
pnpm install
pnpm dev
```

The frontend defaults to `http://127.0.0.1:8000` for the backend API. To point it
at a different backend, create `frontend/.env.local`:

```bash
VITE_API_BASE_URL=http://127.0.0.1:8000
```

Frontend checks:

```bash
cd frontend
pnpm lint
pnpm typecheck
pnpm build
```

More frontend detail is in [frontend/README.md](frontend/README.md).

## Common Commands

```bash
docker compose up --build
docker compose up server worker lease-reaper postgres
docker compose up frontend server worker lease-reaper postgres
docker compose down
```

To reset the local Docker database, remove the Compose volume:

```bash
docker compose down --volumes
```

## Documentation Map

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) describes the implemented
  distributed queue architecture, delivery semantics, data model, observability,
  and production trade-offs.
- [docs/CRUD_SERVER.md](docs/CRUD_SERVER.md) describes the baseline authenticated
  job API server that the queue builds on.
- [docs/WORKERS.md](docs/WORKERS.md) describes the worker processing layer,
  lease recovery, retry behavior, and dead-letter handling.
- [backend/README.md](backend/README.md) contains backend setup, database,
  health-check, metrics, and test commands.
- [frontend/README.md](frontend/README.md) contains frontend setup, Docker
  Compose usage, code structure, data flow, and UI conventions.
