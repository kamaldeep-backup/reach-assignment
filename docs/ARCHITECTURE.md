# Distributed Task Queue & Job Processing Platform

This document describes the implemented architecture for a minimal take-home implementation of a distributed task queue and job-processing platform.

The system accepts authenticated JSON jobs from clients, persists them durably, schedules execution across worker processes, supports lease/ack/retry/dead-letter behavior, enforces per-tenant quotas and rate limits, and exposes operational visibility through APIs, WebSockets, Prometheus metrics, worker lifecycle logs, and a responsive dashboard.

## Goals

- Accept JSON job payloads from authenticated clients.
- Persist jobs durably before acknowledging submission.
- Support idempotent job submission with client-provided idempotency keys.
- Execute jobs asynchronously across a fleet of workers.
- Provide at-least-once delivery semantics with explicit worker leases and acknowledgements.
- Recover expired worker leases after worker crashes or process restarts.
- Retry failed jobs with backoff.
- Move terminal failures to a dead-letter queue.
- Enforce per-tenant submission rate limits.
- Enforce per-tenant running-job concurrency quotas.
- Expose job status APIs, including `DEAD_LETTERED` filtering for DLQ visibility.
- Push real-time job status updates to the dashboard through WebSockets.
- Provide basic observability through Prometheus metrics, job history events, and worker lifecycle logs.
- Keep the implementation small enough for a take-home assignment while documenting production trade-offs.

## Final Technology Choices

- **API framework:** FastAPI
- **Database:** Postgres
- **Queue:** Postgres-backed `jobs` table
- **Workers:** Raw Python worker processes
- **Dashboard:** React + TypeScript + Vite
- **Real-time updates:** FastAPI WebSockets backed by Postgres notifications or polling fanout
- **Validation:** Pydantic
- **Authentication:** Email/password dashboard login plus tenant-scoped API keys
- **FastAPI security:** `OAuth2PasswordBearer`, `OAuth2PasswordRequestForm`, and `APIKeyHeader`
- **Rate limiting:** Postgres-backed fixed-window counters
- **Concurrency quotas:** Postgres transactional counters per tenant
- **Metrics:** Prometheus-compatible `/metrics`
- **Tracing:** Lightweight trace IDs and span-style JSON logs using the Python standard library; OpenTelemetry export is a future production improvement
- **Logging:** Structured JSON HTTP request logs with request IDs, trace IDs, worker lifecycle logs, and job-event correlation metadata
- **Local runtime:** Docker Compose

## High-Level Architecture

```mermaid
flowchart LR
  Client[Authenticated Client] --> API[FastAPI API]
  Dashboard[Responsive Dashboard] --> API
  Dashboard <-->|WebSocket| Realtime[Status Stream]

  API --> DB[(Postgres)]
  API --> Metrics[Prometheus Metrics]
  DB --> Scheduler[Lease Scheduler]
  Scheduler --> WorkerA[Worker Process A]
  Scheduler --> WorkerB[Worker Process B]
  Scheduler --> WorkerN[Worker Process N]

  WorkerA --> DB
  WorkerB --> DB
  WorkerN --> DB

  DB --> DLQ[Dead Letter Queue]
  DB --> Realtime
```

## Responsibilities

### API Service

The API service is responsible for client-facing operations.

It does:

- authenticate dashboard users with email/password access tokens
- authenticate direct API clients with tenant-scoped API keys
- validate job submission requests
- enforce per-tenant submission rate limits
- enforce idempotency keys at job submission time
- persist jobs in Postgres
- return `202 Accepted` once a job is durably stored
- expose job status endpoints
- expose DLQ visibility through `GET /jobs?status=DEAD_LETTERED`, job details, job events, metrics, and dashboard filters
- expose tenant quota visibility through `GET /auth/me`, `GET /api/v1/metrics/summary`, and `/metrics`
- expose Prometheus metrics
- publish job status changes for dashboard updates

It does not:

- execute jobs in the request path
- hold jobs only in memory
- depend on a worker being available before accepting a job
- claim jobs without transactional locking

This keeps submission fast and durable.

### Worker Processes

Worker processes execute jobs from the durable queue.

They do:

- claim eligible jobs using `FOR UPDATE SKIP LOCKED`
- acquire a time-bounded lease
- increment the job attempt count
- enforce per-tenant running-job concurrency quotas before execution
- execute the job handler
- acknowledge successful jobs
- retry failed jobs with backoff
- release tenant concurrency slots after completion or failure
- move exhausted jobs to the DLQ
- emit lifecycle logs and Prometheus metrics

Workers are safe to run as multiple processes because job claiming and tenant counters are updated transactionally.

### Lease Reaper

The lease reaper recovers jobs that were leased by workers that crashed or stopped responding.

It does:

- find jobs in `RUNNING` state whose `lease_expires_at` is in the past
- release their tenant concurrency slots if still held
- retry the jobs if attempts remain
- move them to the DLQ if attempts are exhausted
- record timeout information in job history

This gives the platform at-least-once delivery after worker failure.

### Dashboard

The dashboard provides a small operational UI for queue management.

It does:

- allow users to register and log in with email/password
- create the initial tenant during registration
- let authenticated users create, view, and revoke tenant API keys
- submit jobs for the authenticated user's tenant
- show pending, running, completed, failed, and dead-lettered jobs through status filters
- show per-tenant quota and rate-limit state
- show retry attempts, lease owner, next run time, and last error
- receive real-time job status updates over WebSockets
- adapt to desktop, tablet, and mobile layouts

The dashboard is intentionally operational, not marketing-oriented.

## End-To-End Flow

1. A client sends `POST /jobs` with a JSON payload and an `Idempotency-Key` header.
2. FastAPI authenticates either the dashboard user's access token or a tenant API key and resolves the tenant.
3. The API checks the tenant's submission rate limit.
4. The API inserts a job row into `jobs`.
5. If the same tenant and idempotency key already exist, the existing job is returned.
6. The API records a `SUBMITTED` status event in `job_events`.
7. The API returns `202 Accepted` with the job ID and current status.
8. A worker claims an eligible pending job in a Postgres transaction.
9. The worker checks and increments the tenant's running-job counter.
10. The worker marks the job `RUNNING`, sets `locked_by`, generates a fresh `lease_id`, and sets `lease_expires_at`.
11. The worker executes the job handler.
12. If execution succeeds, the worker marks the job `SUCCEEDED`.
13. If execution fails and attempts remain, the worker marks the job `PENDING` and schedules `run_after` using backoff.
14. If execution fails and attempts are exhausted, the worker marks the job `DEAD_LETTERED` and inserts a row into `dead_letter_jobs`.
15. Every state transition is recorded in `job_events`.
16. The WebSocket broadcaster pushes job updates to connected dashboard clients.
17. Prometheus metrics, structured JSON logs, lightweight trace spans, and job history events capture queue depth, job latency, retries, failures, and worker behavior. OpenTelemetry export is intentionally left as future production work.

## Delivery Semantics

The platform provides **at-least-once execution**.

At-least-once is chosen because it is realistic for a small distributed queue and can be implemented correctly with Postgres leases. A job may execute more than once if:

- a worker completes external side effects but crashes before acking the job
- a worker lease expires while the job is still running
- an ack transaction fails after the handler succeeds

Clients are expected to provide idempotency keys at submission time, and job handlers should be idempotent for external side effects. The platform prevents duplicate job creation for the same tenant and idempotency key, but it does not claim exactly-once side-effect execution.

## Database Relationship Diagram

```mermaid
erDiagram
  USERS ||--o{ TENANT_USERS : "belongs through"
  TENANTS ||--o{ TENANT_USERS : "has members"
  USERS ||--o{ API_KEYS : "creates"
  TENANTS ||--o{ API_KEYS : "authenticates with"
  TENANTS ||--o{ JOBS : "owns"
  TENANTS ||--o{ TENANT_RATE_LIMITS : "has"
  TENANTS ||--o{ TENANT_RUNTIME_QUOTAS : "has"
  JOBS ||--o{ JOB_EVENTS : "records"
  JOBS ||--o| DEAD_LETTER_JOBS : "can end in"

  USERS {
    uuid id PK
    text email
    text password_hash
    boolean is_active
    timestamptz created_at
    timestamptz last_login_at
  }

  TENANTS {
    uuid id PK
    text name
    int max_running_jobs
    int submit_rate_limit
    boolean is_active
    timestamptz created_at
  }

  TENANT_USERS {
    uuid tenant_id FK
    uuid user_id FK
    text role
    timestamptz created_at
  }

  API_KEYS {
    uuid id PK
    uuid tenant_id FK
    uuid created_by_user_id FK
    text key_hash
    text name
    text key_prefix
    text scopes
    boolean is_active
    timestamptz expires_at
    timestamptz last_used_at
    timestamptz created_at
    timestamptz revoked_at
  }

  JOBS {
    uuid id PK
    uuid tenant_id FK
    text idempotency_key
    jsonb payload
    job_status status
    int priority
    int attempts
    int max_attempts
    timestamptz run_after
    timestamptz lease_expires_at
    text locked_by
    uuid lease_id
    text last_error
    timestamptz created_at
    timestamptz updated_at
    timestamptz completed_at
  }

  JOB_EVENTS {
    uuid id PK
    uuid job_id FK
    uuid tenant_id FK
    text event_type
    job_status from_status
    job_status to_status
    text message
    jsonb metadata
    timestamptz created_at
  }

  DEAD_LETTER_JOBS {
    uuid id PK
    uuid job_id FK
    uuid tenant_id FK
    jsonb payload
    text final_error
    int attempts
    timestamptz dead_lettered_at
  }

  TENANT_RATE_LIMITS {
    uuid tenant_id PK,FK
    int window_start_epoch
    int request_count
    timestamptz updated_at
  }

  TENANT_RUNTIME_QUOTAS {
    uuid tenant_id PK,FK
    int running_jobs
    timestamptz updated_at
  }
```

## Database Schema

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TYPE job_status AS ENUM (
  'PENDING',
  'RUNNING',
  'SUCCEEDED',
  'FAILED',
  'DEAD_LETTERED',
  'CANCELLED'
);

CREATE TABLE tenants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  max_running_jobs INT NOT NULL DEFAULT 5,
  submit_rate_limit INT NOT NULL DEFAULT 60,
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_login_at TIMESTAMPTZ
);

CREATE TABLE tenant_users (
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'owner',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, user_id)
);

CREATE TABLE api_keys (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  key_hash TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  key_prefix TEXT NOT NULL,
  scopes TEXT[] NOT NULL DEFAULT ARRAY['jobs:read', 'jobs:write'],
  is_active BOOLEAN NOT NULL DEFAULT true,
  expires_at TIMESTAMPTZ,
  last_used_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  revoked_at TIMESTAMPTZ
);

CREATE TABLE jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  idempotency_key TEXT NOT NULL,
  payload JSONB NOT NULL,
  status job_status NOT NULL DEFAULT 'PENDING',
  priority INT NOT NULL DEFAULT 0,
  attempts INT NOT NULL DEFAULT 0,
  max_attempts INT NOT NULL DEFAULT 3,
  run_after TIMESTAMPTZ NOT NULL DEFAULT now(),
  lease_expires_at TIMESTAMPTZ,
  locked_by TEXT,
  lease_id UUID,
  last_error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  UNIQUE (tenant_id, idempotency_key)
);

CREATE TABLE job_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  event_type TEXT NOT NULL,
  from_status job_status,
  to_status job_status,
  message TEXT,
  metadata JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE dead_letter_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id UUID NOT NULL UNIQUE REFERENCES jobs(id) ON DELETE CASCADE,
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  payload JSONB NOT NULL,
  final_error TEXT NOT NULL,
  attempts INT NOT NULL,
  dead_lettered_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE tenant_rate_limits (
  tenant_id UUID PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
  window_start_epoch INT NOT NULL,
  request_count INT NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE tenant_runtime_quotas (
  tenant_id UUID PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
  running_jobs INT NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_jobs_claim
ON jobs (status, run_after, priority DESC, created_at)
WHERE status = 'PENDING';

CREATE INDEX idx_jobs_running_lease
ON jobs (status, lease_expires_at)
WHERE status = 'RUNNING';

CREATE INDEX idx_jobs_tenant_status
ON jobs (tenant_id, status, created_at DESC);

CREATE INDEX idx_job_events_job_id
ON job_events (job_id, created_at DESC);

CREATE INDEX idx_dead_letter_jobs_tenant
ON dead_letter_jobs (tenant_id, dead_lettered_at DESC);
```

The current worker implementation deliberately uses a narrow active state
machine:

```text
PENDING -> RUNNING -> SUCCEEDED
PENDING -> RUNNING -> PENDING         # retry with backoff
PENDING -> RUNNING -> DEAD_LETTERED   # exhausted or non-retryable failure
```

`FAILED` and `CANCELLED` are retained in the enum as reserved states. They keep
the API and schema compatible with future workflows such as manual cancellation,
operator-forced terminal failure, or a separate "failed but not dead-lettered"
state. The take-home implementation does not expose cancel endpoints and does
not set `FAILED` from worker execution; retryable failures are requeued and
exhausted or non-retryable failures go to `DEAD_LETTERED`.

## Postgres Queue Design

Jobs are stored in the `jobs` table. A job is eligible for execution when:

```text
jobs.status = 'PENDING'
jobs.run_after <= now()
```

Workers claim jobs using `FOR UPDATE SKIP LOCKED`, allowing many worker processes to compete safely without blocking each other.

```sql
SELECT id
FROM jobs
JOIN tenants ON tenants.id = jobs.tenant_id
LEFT JOIN tenant_runtime_quotas q ON q.tenant_id = jobs.tenant_id
WHERE status = 'PENDING'
  AND run_after <= now()
  AND COALESCE(q.running_jobs, 0) < tenants.max_running_jobs
ORDER BY priority DESC, created_at
FOR UPDATE SKIP LOCKED
LIMIT 10;
```

After selecting a candidate job, the worker attempts to reserve tenant concurrency and lease the job in the same transaction.

```sql
UPDATE tenant_runtime_quotas q
SET running_jobs = running_jobs + 1,
    updated_at = now()
FROM tenants t
WHERE q.tenant_id = t.id
  AND q.tenant_id = $1
  AND q.running_jobs < t.max_running_jobs;
```

If the quota update succeeds, the worker marks the job as running:

```sql
UPDATE jobs
SET status = 'RUNNING',
    attempts = attempts + 1,
    locked_by = $1,
    lease_id = $2,
    lease_expires_at = now() + ($3 || ' seconds')::interval,
    updated_at = now()
WHERE id = $4
  AND status = 'PENDING';
```

If the quota update does not affect a row, the worker skips that tenant's job and tries another eligible job.

## Ack, Retry, Lease, And DLQ Semantics

### Successful Ack

When a job succeeds, the worker marks it complete and releases the tenant concurrency slot in a transaction.

```sql
UPDATE jobs
SET status = 'SUCCEEDED',
    lease_expires_at = NULL,
    locked_by = NULL,
    lease_id = NULL,
    completed_at = now(),
    updated_at = now()
WHERE id = $1
  AND status = 'RUNNING'
  AND locked_by = $2
  AND lease_id = $3
  AND lease_expires_at > now();
```

### Retryable Failure

When a job fails and attempts remain, it is returned to `PENDING` with exponential backoff.

```sql
UPDATE jobs
SET status = 'PENDING',
    run_after = now() + ($1 || ' seconds')::interval,
    lease_expires_at = NULL,
    locked_by = NULL,
    lease_id = NULL,
    last_error = $2,
    updated_at = now()
WHERE id = $3
  AND status = 'RUNNING'
  AND locked_by = $4
  AND lease_id = $5
  AND lease_expires_at > now();
```

Backoff can be:

```text
delay_seconds = min(300, 2 ^ attempts + jitter)
```

### Dead-Letter Failure

When a job exhausts `max_attempts`, it is marked `DEAD_LETTERED` and copied into `dead_letter_jobs`.

```sql
UPDATE jobs
SET status = 'DEAD_LETTERED',
    lease_expires_at = NULL,
    locked_by = NULL,
    lease_id = NULL,
    last_error = $1,
    completed_at = now(),
    updated_at = now()
WHERE id = $2
  AND status = 'RUNNING'
  AND locked_by = $3
  AND lease_id = $4
  AND lease_expires_at > now();
```

```sql
INSERT INTO dead_letter_jobs (job_id, tenant_id, payload, final_error, attempts)
SELECT id, tenant_id, payload, last_error, attempts
FROM jobs
WHERE id = $1
ON CONFLICT (job_id) DO NOTHING;
```

### Expired Lease Recovery

A lease is expired when:

```text
jobs.status = 'RUNNING'
jobs.lease_expires_at < now()
```

The lease reaper treats this as a failed attempt. If attempts remain, the job becomes `PENDING` again. If attempts are exhausted, the job moves to the DLQ.

The key edge case is that a slow worker may still finish after its lease expires. Ack, retry, and DLQ updates include `locked_by`, `lease_id`, `status = 'RUNNING'`, and a live `lease_expires_at` guard, so a stale worker cannot update a job it no longer owns after another worker has reclaimed it or after the lease has expired.

## Authentication And API Keys

The platform has two authentication paths.

Dashboard users authenticate with email and password:

1. A user registers with email, password, and tenant name.
2. The server creates a `users` row, hashes the password, creates a `tenants` row, and creates an owner row in `tenant_users`.
3. The user logs in through `POST /auth/login`.
4. The login endpoint uses FastAPI's `OAuth2PasswordRequestForm`.
5. The server verifies the password hash and returns a signed bearer access token.
6. Dashboard API calls use `OAuth2PasswordBearer` to resolve the current user and tenant.

Direct API clients authenticate with tenant-scoped API keys:

1. A logged-in dashboard user creates an API key from the dashboard.
2. The server generates a random key such as `tqk_live_ab12_generated-secret`.
3. The database stores only a hash of the key plus a short display prefix.
4. Direct clients send the key in `X-API-Key`.
5. FastAPI's `APIKeyHeader` dependency resolves the key to a tenant and scopes the request.

The client never sends `tenant_id` as trusted input for job APIs. Tenant ownership is always derived server-side from either the dashboard access token or the API key.

## Idempotency

The API requires an `Idempotency-Key` header on job submission.

Idempotency is scoped by tenant:

```text
UNIQUE (tenant_id, idempotency_key)
```

If a client retries the same submission with the same key, the API returns the existing job instead of creating a duplicate.

This provides duplicate-submit protection, but it does not provide exactly-once execution of external side effects. The platform documents at-least-once delivery and expects job handlers to be idempotent.

## Tenant Rate Limiting

For the take-home, submission rate limits use a Postgres-backed fixed window.

Each tenant has:

```text
tenants.submit_rate_limit = max accepted submissions per minute
```

On each job submission:

1. Compute the current minute epoch.
2. Lock or upsert the tenant's row in `tenant_rate_limits`.
3. Reset the counter if the stored window is old.
4. Increment the counter if the tenant is below the limit.
5. Reject with `429 Too Many Requests` if the tenant is above the limit.

This is simple, durable, and reproducible for the assignment. In production, Redis or an API gateway would usually be better for high-volume rate limiting.

## Tenant Concurrency Quotas

Each tenant has a maximum number of jobs that may run at the same time:

```text
tenants.max_running_jobs
```

Workers increment `tenant_runtime_quotas.running_jobs` before marking a job `RUNNING`. They decrement it when a job succeeds, is scheduled for retry, is dead-lettered, or is recovered by the lease reaper.

This prevents one tenant from consuming all workers.

## Autoscaling Triggers

The take-home intentionally implements autoscaling as metrics plus documented
scaling rules rather than real infrastructure automation. That keeps the scope
focused on queue correctness, leases, retries, DLQ behavior, quotas, and
observability while still showing how workers would be scaled in production.

Implemented scaling signals:

- `queue_depth{tenant_id,status="PENDING"}`
- `oldest_pending_age_seconds{tenant_id}`
- `running_jobs{tenant_id}`
- `tenant_running_limit{tenant_id}`
- `tenant_runtime_slots_used{tenant_id}`
- `job_execution_duration_seconds_bucket{tenant_id,job_type,outcome}`
- `jobs_retried_total{tenant_id}`
- `jobs_dead_lettered_total{tenant_id}`

Queue capacity is exposed through tenant quota gauges instead of a separate
`worker_available_capacity` metric:

```text
tenant_available_runtime_slots =
  max(tenant_running_limit - tenant_runtime_slots_used, 0)

tenant_runtime_utilization =
  tenant_runtime_slots_used / tenant_running_limit
```

That is a deliberate simplification. The current system has one-job-at-a-time
worker processes and tenant-level concurrency quotas, so tenant runtime slots
are the authoritative capacity signal. A production deployment could add
process-level worker heartbeats and a separate `worker_available_capacity`
gauge if workers process multiple jobs concurrently or expose richer health.

Example conceptual policy:

```text
Scale out workers when:
- sum(queue_depth{status="PENDING"}) > 100 for 3 minutes, or
- max(oldest_pending_age_seconds) > 60 seconds, or
- average tenant_runtime_utilization > 80%.

Scale in workers when:
- sum(queue_depth{status="PENDING"}) < 10 for 10 minutes, and
- max(oldest_pending_age_seconds) < 10 seconds, and
- average tenant_runtime_utilization < 30%.
```

For Docker Compose, scaling is demonstrated manually:

```bash
docker compose up --scale worker=4
```

For Kubernetes, the equivalent production direction would be an HPA/KEDA-style
policy using Prometheus metrics. Example rule, expressed conceptually:

```yaml
scaleTargetRef:
  name: worker
triggers:
  - type: prometheus
    metric: pending_jobs
    query: sum(queue_depth{status="PENDING"})
    threshold: "100"
  - type: prometheus
    metric: oldest_pending_age
    query: max(oldest_pending_age_seconds)
    threshold: "60"
  - type: prometheus
    metric: tenant_runtime_utilization
    query: avg(tenant_runtime_slots_used / tenant_running_limit)
    threshold: "0.8"
```

The repository does not include Kubernetes manifests or KEDA installation
because that would add deployment-specific infrastructure beyond the assignment
scope.

## Observability

### Metrics

The API exposes Prometheus metrics at:

```text
GET /metrics
```

Implemented metrics:

```text
jobs_submitted_total{tenant_id}
jobs_claimed_total{tenant_id,worker_id}
jobs_succeeded_total{tenant_id,worker_id}
jobs_retried_total{tenant_id}
jobs_dead_lettered_total{tenant_id}
job_lease_expired_total{tenant_id}
tenant_rate_limited_total{tenant_id}
queue_depth{tenant_id,status}
running_jobs{tenant_id}
dead_letter_jobs{tenant_id}
oldest_pending_age_seconds{tenant_id}
tenant_running_limit{tenant_id}
tenant_runtime_slots_used{tenant_id}
job_execution_duration_seconds_bucket{tenant_id,job_type,outcome}
job_queue_wait_seconds_bucket{tenant_id,job_type}
```

The effective available capacity per tenant is derived as:

```text
max(tenant_running_limit{tenant_id} - tenant_runtime_slots_used{tenant_id}, 0)
```

The dashboard uses `GET /api/v1/metrics/summary` for tenant-scoped operational
counts instead of deriving counts from a paginated jobs list.

### Tracing

The take-home implements dependency-free trace correlation rather than a full
OpenTelemetry SDK. HTTP middleware accepts or generates `X-Request-ID` and
`X-Trace-ID`, returns both headers on API responses, and stores the values in
request-local context. API and worker code use small span helpers that emit
`trace.span.start` and `trace.span.end` JSON log records with span IDs,
durations, outcomes, and relevant attributes.

`POST /jobs` writes the current `requestId` and `traceId` into the
`SUBMITTED` job event. Worker claim, retry, success, DLQ, and lease-reaper
events propagate those metadata fields so a single submitted job can be
followed across API and worker processes through `job_events` and logs.

Implemented lightweight spans include:

- auth register/login and credential resolution
- job idempotency lookup
- submission rate-limit reservation
- job insert
- worker handler execution
- API key create/revoke
- lease reaper recovery

Useful trace/log attributes include:

```text
tenant.id
job.id
job.status
job.attempt
worker.id
idempotency.key
request.id
trace.id
```

This is intentionally not wire-compatible distributed tracing. A production
version should replace or bridge the helpers with OpenTelemetry instrumentation,
exporters, and a trace backend.

### Logging

The API emits structured JSON logs for every HTTP request. Request logs include
method, path, status code, duration, `requestId`, and `traceId`. Application
events such as registration, login, job submission, rate limiting, duplicate
idempotency returns, API key creation/revocation, worker execution, retries,
DLQ moves, and lease recovery also use structured JSON log records.

Centralized log aggregation is intentionally out of scope for the take-home,
but the log format is machine-readable and can be shipped to a production log
backend later.

Useful future log improvements:

- tenant concurrency quota reached
- WebSocket connection lifecycle events
- request and job correlation in a centralized log backend
- structured exception stack traces for unexpected server errors

## API Endpoints

Route handlers should stay thin. Authentication, request validation, HTTP status codes, and response serialization belong in the API layer; SQLAlchemy queries and database writes belong in repositories such as `app/repositories/users.py`, `app/repositories/api_keys.py`, and `app/repositories/jobs.py`.

### `POST /auth/register`

Creates a dashboard user and an initial tenant.

Request:

```json
{
  "email": "admin@acme.com",
  "password": "correct-horse-battery-staple",
  "tenantName": "Acme Corp"
}
```

Response:

```json
{
  "userId": "uuid",
  "tenantId": "uuid",
  "email": "admin@acme.com"
}
```

The password is hashed before storage. The raw password is never stored.

### `POST /auth/login`

Logs a dashboard user in using FastAPI's `OAuth2PasswordRequestForm` shape.

Request content type:

```text
application/x-www-form-urlencoded
```

Form fields:

```text
username=admin@acme.com
password=correct-horse-battery-staple
```

Response:

```json
{
  "access_token": "signed-access-token",
  "token_type": "bearer"
}
```

The dashboard stores this access token in memory or browser storage and sends it as:

```text
Authorization: Bearer signed-access-token
```

### `GET /auth/me`

Returns the current dashboard user and tenant context.

### `POST /api-keys`

Creates a tenant-scoped API key for direct API access.

This endpoint requires dashboard user authentication.

Request:

```json
{
  "name": "CI integration",
  "scopes": ["jobs:read", "jobs:write"],
  "expiresAt": null
}
```

Response:

```json
{
  "apiKeyId": "uuid",
  "name": "CI integration",
  "keyPrefix": "tqk_live_ab12",
  "apiKey": "tqk_live_ab12_generated-secret",
  "scopes": ["jobs:read", "jobs:write"]
}
```

The raw API key is shown only once. The database stores only `key_hash`.

### `GET /api-keys`

Lists API keys for the authenticated user's tenant. Raw key values are never returned.

### `DELETE /api-keys/{api_key_id}`

Revokes an API key by setting `is_active = false` and `revoked_at = now()`.

### `POST /jobs`

Submits a job.

Headers, using one of the authentication options:

```text
Authorization: Bearer signed-access-token
or
X-API-Key: tqk_live_generated-secret
Idempotency-Key: client-generated-key
```

Dashboard requests use `Authorization`. Direct API clients use `X-API-Key`. The server accepts either credential type and derives the tenant from the credential.

Request:

```json
{
  "type": "send_email",
  "payload": {
    "to": "customer@example.com",
    "template": "welcome"
  },
  "priority": 0
}
```

Response:

```json
{
  "jobId": "generated-uuid",
  "status": "PENDING",
  "idempotencyKey": "client-generated-key"
}
```

### `GET /jobs/{job_id}`

Returns job status and execution metadata.

```json
{
  "jobId": "uuid",
  "tenantId": "uuid",
  "status": "RUNNING",
  "attempts": 1,
  "maxAttempts": 3,
  "runAfter": "2026-04-30T10:00:00Z",
  "leaseExpiresAt": "2026-04-30T10:05:00Z",
  "lockedBy": "worker-1",
  "lastError": null,
  "createdAt": "2026-04-30T09:59:00Z",
  "updatedAt": "2026-04-30T10:00:10Z"
}
```

### `GET /jobs`

Lists jobs for the authenticated tenant.

Query parameters:

```text
status=PENDING|RUNNING|SUCCEEDED|FAILED|DEAD_LETTERED|CANCELLED
limit=50
```

### `GET /jobs/{job_id}/events`

Returns the job status history.

### DLQ visibility

Dedicated DLQ APIs are intentionally out of scope for the take-home. DLQ visibility is available through the existing job and metrics surfaces:

- `GET /jobs?status=DEAD_LETTERED` lists dead-lettered jobs for the authenticated tenant.
- `GET /jobs/{job_id}` shows the job payload, status, attempts, `lastError`, and completion metadata.
- `GET /jobs/{job_id}/events` shows `DEAD_LETTERED`, `LEASE_EXPIRED`, and retry history events.
- `GET /api/v1/metrics/summary` and `/metrics` expose dead-letter counts.
- The dashboard jobs view includes `DEAD_LETTERED` in its status filters.

DLQ requeue is future operator tooling. The current implementation preserves terminal failure context in `dead_letter_jobs` but does not expose a requeue endpoint.

### Tenant quota visibility

The authenticated tenant's configured limits are returned by `GET /auth/me`. Runtime queue counts are returned by `GET /api/v1/metrics/summary`, and full Prometheus gauges are returned by `/metrics`.

### `GET /health`

Returns service health.

### `GET /metrics`

Returns Prometheus metrics.

### `GET /api/v1/metrics/summary`

Returns tenant-scoped database-backed queue counts for the dashboard.

### `WS /api/v1/jobs/stream`

Streams job status updates for the authenticated tenant.

Example message:

```json
{
  "type": "job.event",
  "job": {
    "jobId": "uuid",
    "status": "RUNNING",
    "attempts": 1
  },
  "event": {
    "eventType": "CLAIMED",
    "fromStatus": "PENDING",
    "toStatus": "RUNNING"
  }
}
```

## Dashboard Views

The dashboard should be responsive across desktop, tablet, and mobile.

It includes:

- registration and login screens
- tenant identity display after login
- API key management view
- submit job form with JSON editor
- queue summary counters
- pending jobs table or stacked mobile list
- running jobs view with lease owner and lease expiry
- completed jobs view
- failed and retrying jobs view
- dead-lettered job visibility through the `DEAD_LETTERED` status filter, job details, `lastError`, events, and metrics
- tenant quota panel
- live status updates through WebSockets

Desktop layout can use a sidebar plus dense tables. Tablet can use tabs with compact tables. Mobile should use stacked cards and filters.

## Proposed Code Structure

```text
.
├── README.md
├── ARCHITECTURE.md
├── docker-compose.yml
├── pyproject.toml
├── .env.example
├── backend
│   ├── app
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── api
│   │   │   ├── __init__.py
│   │   │   ├── auth.py
│   │   │   ├── api_keys.py
│   │   │   ├── jobs.py
│   │   │   ├── health.py
│   │   │   ├── metrics.py
│   │   │   └── websockets.py
│   │   ├── domain
│   │   │   ├── __init__.py
│   │   │   ├── schemas.py
│   │   │   └── statuses.py
│   │   ├── repositories
│   │   │   ├── __init__.py
│   │   │   ├── users.py
│   │   │   ├── api_keys.py
│   │   │   ├── jobs.py
│   │   │   └── tenants.py
│   │   ├── services
│   │   │   ├── __init__.py
│   │   │   ├── auth.py
│   │   │   ├── password_hashing.py
│   │   │   ├── access_tokens.py
│   │   │   ├── api_keys.py
│   │   │   ├── rate_limits.py
│   │   │   ├── quotas.py
│   │   │   ├── job_submission.py
│   │   │   ├── job_execution.py
│   │   │   └── status_broadcaster.py
│   │   ├── observability
│   │   │   ├── __init__.py
│   │   │   └── metrics.py
│   │   └── workers
│   │       ├── __init__.py
│   │       ├── worker.py
│   │       ├── lease_reaper.py
│   │       └── handlers.py
│   └── migrations
│       └── 001_initial_schema.sql
├── frontend
│   ├── package.json
│   ├── index.html
│   └── src
│       ├── main.tsx
│       ├── api
│       │   └── client.ts
│       ├── components
│       │   ├── JobForm.tsx
│       │   ├── JobList.tsx
│       │   ├── QueueSummary.tsx
│       │   ├── QuotaPanel.tsx
│       │   └── DlqView.tsx
│       └── styles.css
└── tests
    ├── test_jobs_api.py
    ├── test_idempotency.py
    ├── test_rate_limits.py
    ├── test_concurrency_quotas.py
    ├── test_worker_ack_retry_dlq.py
    ├── test_lease_expiry.py
    └── test_durability.py
```

## Docker Compose

For the take-home, Docker Compose can run Postgres, the API, the worker, the lease reaper, and the dashboard.

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: queue
      POSTGRES_PASSWORD: queue
      POSTGRES_DB: task_queue
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U queue -d task_queue"]
      interval: 5s
      timeout: 5s
      retries: 5

  api:
    build:
      context: .
      dockerfile: backend/Dockerfile
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000
    env_file:
      - .env
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy

  worker:
    build:
      context: .
      dockerfile: backend/Dockerfile
    command: python -m app.workers.worker
    env_file:
      - .env
    depends_on:
      postgres:
        condition: service_healthy

  lease-reaper:
    build:
      context: .
      dockerfile: backend/Dockerfile
    command: python -m app.workers.lease_reaper
    env_file:
      - .env
    depends_on:
      postgres:
        condition: service_healthy

  dashboard:
    build:
      context: frontend
    ports:
      - "5173:5173"
    environment:
      VITE_API_URL: http://localhost:8000
      VITE_WS_URL: ws://localhost:8000/ws/jobs
    depends_on:
      - api

volumes:
  postgres_data:
```

## Local Commands

Start the platform:

```bash
docker compose up --build
```

Scale workers:

```bash
docker compose up --scale worker=4
```

Register a dashboard user and tenant:

```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@acme.com",
    "password": "correct-horse-battery-staple",
    "tenantName": "Acme Corp"
  }'
```

Log in:

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin@acme.com&password=correct-horse-battery-staple"
```

Create an API key:

```bash
curl -X POST http://localhost:8000/api-keys \
  -H "Authorization: Bearer signed-access-token" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "local curl client",
    "scopes": ["jobs:read", "jobs:write"],
    "expiresAt": null
  }'
```

Submit a job:

```bash
curl -X POST http://localhost:8000/jobs \
  -H "X-API-Key: tqk_live_generated-secret" \
  -H "Idempotency-Key: welcome-email-001" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "send_email",
    "payload": {
      "to": "customer@example.com",
      "template": "welcome"
    },
    "priority": 0,
    "maxAttempts": 3
  }'
```

Expected response:

```json
{
  "jobId": "generated-uuid",
  "status": "PENDING",
  "idempotencyKey": "welcome-email-001"
}
```

Check status:

```bash
curl http://localhost:8000/jobs/generated-uuid \
  -H "X-API-Key: tqk_live_generated-secret"
```

Open the dashboard:

```text
http://localhost:5173
```

## Configuration

Example `.env.example`:

```bash
DATABASE_URL=postgresql://queue:queue@postgres:5432/task_queue
PASSWORD_HASH_SCHEME=argon2
ACCESS_TOKEN_SECRET=replace-me
ACCESS_TOKEN_EXPIRE_MINUTES=60
API_KEY_PEPPER=replace-me
WORKER_POLL_INTERVAL_SECONDS=1
WORKER_LEASE_SECONDS=60
JOB_MAX_ATTEMPTS=3
JOB_BACKOFF_MAX_SECONDS=300
LEASE_REAPER_INTERVAL_SECONDS=10
RATE_LIMIT_WINDOW_SECONDS=60
OTEL_SERVICE_NAME=task-queue-platform
ENABLE_JSON_LOGS=true
```

## Error Handling

Retryable failures:

- temporary database errors
- transient network failures in job handlers
- handler timeouts
- process crashes before ack
- expired worker leases

Terminal failures:

- job payload cannot be handled
- handler raises a non-retryable error
- job exceeds `max_attempts`
- job repeatedly times out

Terminal failures are preserved in `dead_letter_jobs` with the original payload, final error, and attempt count.

## Testing Strategy

The tests should focus on correctness rather than only endpoint coverage.

Required tests:

- user registration creates a tenant and owner membership
- login rejects invalid passwords and returns an access token for valid credentials
- API keys are shown only at creation time and stored only as hashes
- revoked or expired API keys cannot access job APIs
- job submission persists jobs before returning
- duplicate idempotency keys return the original job
- tenant rate limits reject excess submissions
- tenant concurrency quotas prevent excess running jobs
- workers claim jobs without double-claiming under concurrency
- successful jobs are acknowledged and marked `SUCCEEDED`
- failed jobs retry with backoff
- exhausted jobs move to DLQ
- expired leases are recovered
- stale workers cannot ack jobs they no longer own
- jobs survive API and worker process restarts because state is stored in Postgres
- WebSocket clients receive status updates

Stress test:

- insert many jobs for multiple tenants
- start multiple workers
- verify no job has overlapping successful leases
- verify tenant running counts never exceed configured quotas

## Tradeoffs For The Take-Home

### Deliberate Simplifications

- Postgres is used as both durable job store and queue.
- Email/password auth is implemented locally instead of using a full identity provider.
- Access tokens are simple signed bearer tokens instead of a complete OAuth server.
- Fixed-window rate limiting is used instead of a distributed token bucket.
- Workers are raw Python loops instead of Celery, Dramatiq, Sidekiq, or Temporal.
- Autoscaling automation is intentionally out of scope; the implementation exposes Prometheus metrics, documents scaling policies, and supports manual Docker Compose scaling.
- Worker capacity is represented by tenant runtime quota metrics rather than a separate worker-heartbeat capacity model.
- `FAILED` and `CANCELLED` are reserved job states; the current worker flow retries or dead-letters instead of exposing final-failed or cancel workflows.
- WebSocket fanout can be backed by polling or Postgres notifications instead of Redis Pub/Sub.
- Dedicated DLQ inspection and requeue APIs are intentionally out of scope; DLQ visibility is provided through `DEAD_LETTERED` job filtering, job details, job events, dashboard filters, and metrics.
- OpenTelemetry export, a collector, and a trace backend are intentionally out of scope; the take-home uses lightweight trace IDs, span-style JSON logs, and request ID propagation.
- Job handlers can be simple demo handlers instead of executing arbitrary untrusted code.
- The dashboard is minimal but operationally useful.
- Multi-region behavior is out of scope.

### Production Improvements

Before production, I would add:

- managed queue infrastructure such as SQS, RabbitMQ, Kafka, or Redis Streams depending on workload
- SSO/OIDC support and stronger tenant/user administration
- API key rotation workflows and fine-grained key scopes
- payload size limits and object storage for large payloads
- a true distributed rate limiter
- worker heartbeats separate from lease expiry
- poison-job detection and richer DLQ replay tooling
- tenant-level fairness scheduling
- priority queues with starvation protection
- handler-level idempotency contracts
- schema validation per job type
- OpenTelemetry collector and trace backend
- Prometheus and Grafana dashboards
- alerts for queue depth, oldest pending job age, DLQ growth, and retry spikes
- database partitioning for large job and event tables
- retention policies for completed jobs and job events
- audit logs for dashboard actions
- deployment manifests for Kubernetes or ECS
