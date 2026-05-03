# Worker Processing Layer

This document outlines the worker side of the take-home project. It describes the next layer after the baseline CRUD server in `CRUD_SERVER.md`: raw Python worker processes that claim pending jobs from Postgres, execute handlers asynchronously from the API request path, acknowledge successful work, retry transient failures, recover expired leases, and preserve terminal failures in a dead-letter queue.

The current repository implements the API, authentication, durable job submission, job history, worker processes, lease recovery, retry behavior, dead-letter handling, tenant runtime quotas, and worker tests. This document records the implemented worker design and the production trade-offs that remain intentionally out of scope for the take-home.

## Goals

- Execute submitted jobs outside the API request path.
- Keep Postgres as the durable source of truth for queue state.
- Support multiple worker processes without double-claiming jobs.
- Provide at-least-once delivery with explicit leases and acknowledgements.
- Retry failed jobs with bounded exponential backoff.
- Move exhausted jobs into a dead-letter queue.
- Recover jobs whose workers crash or stop renewing leases.
- Enforce per-tenant running-job concurrency quotas.
- Record every worker-driven state transition in `job_events`.
- Keep the worker implementation small, inspectable, and easy to run locally.

## Final Technology Choices

- **Worker runtime:** Raw Python processes
- **Database:** Postgres
- **Queue:** Postgres-backed `jobs` table
- **DB access:** SQLAlchemy async sessions using the existing backend configuration
- **Job handlers:** Python functions registered by job type
- **Lease coordination:** `FOR UPDATE SKIP LOCKED`
- **Retries:** Exponential backoff with jitter
- **DLQ:** `dead_letter_jobs` table
- **Configuration:** environment variables loaded through the existing backend settings
- **Local runtime:** Docker Compose
- **Testing:** Pytest with async database tests

## High-Level Architecture

```mermaid
flowchart LR
  API[FastAPI API] --> DB[(Postgres)]

  DB --> Claim[Claim Pending Job]
  Claim --> Quota[Reserve Tenant Slot]
  Quota --> Worker[Worker Process]
  Worker --> Handler[Job Handler Registry]

  Handler --> Ack[Mark Succeeded]
  Handler --> Retry[Schedule Retry]
  Handler --> DLQ[Dead Letter]

  Ack --> DB
  Retry --> DB
  DLQ --> DB

  Reaper[Lease Reaper] --> DB
  Reaper --> Retry
  Reaper --> DLQ
```

## Responsibilities

### Worker Process

The worker owns normal job execution.

It does:

- poll for eligible `PENDING` jobs
- claim one job at a time using transactional row locking
- reserve tenant concurrency before execution
- mark claimed jobs `RUNNING`
- increment `attempts`
- set `locked_by` to the worker ID, generate `lease_id`, and set `lease_expires_at`
- dispatch to a handler based on `job_type`
- mark successful jobs `SUCCEEDED`
- schedule retryable failures back to `PENDING`
- move exhausted failures to `DEAD_LETTERED`
- release tenant concurrency slots
- append job history events for all state transitions

It does not:

- accept client requests
- trust tenant IDs from job payloads
- keep job state only in memory
- delete failed jobs
- acknowledge jobs without checking ownership
- guarantee exactly-once external side effects

### Handler Registry

Handlers own the actual work for a job type.

It does:

- map `job_type` strings to Python callables
- validate handler-specific payload requirements
- return success for completed work
- raise retryable exceptions for transient failures
- raise non-retryable exceptions for permanent failures

It does not:

- mutate queue state directly
- decide lease ownership
- write `job_events`
- bypass tenant isolation

The first implementation can include a small set of demonstration handlers:

```text
send_email   logs an email-like payload instead of sending real mail
webhook      logs a webhook-like payload instead of calling external services
noop         succeeds immediately for smoke tests
fail_once    fails on the first attempt for retry tests
```

### Lease Reaper

The lease reaper owns recovery for workers that crash or stop before acking.

It does:

- find `RUNNING` jobs with expired leases
- release their tenant concurrency slots
- treat the expired lease as a failed attempt
- return jobs to `PENDING` when attempts remain
- move exhausted jobs to the DLQ
- append timeout events to `job_events`

It does not:

- execute job handlers
- steal non-expired leases
- assume a stale worker has stopped executing external side effects

The reaper is what makes crash recovery explicit. A stale worker may still finish after its lease expires, but its ack will fail because it no longer owns a valid `RUNNING` row.

## Worker State Model

The baseline CRUD server currently has:

```text
PENDING
RUNNING
SUCCEEDED
FAILED
CANCELLED
```

The worker layer should extend the model to include terminal dead-letter state:

```text
PENDING
RUNNING
SUCCEEDED
FAILED
DEAD_LETTERED
CANCELLED
```

The current implementation deliberately uses only the states needed for the
core assignment lifecycle:

```text
PENDING -> RUNNING -> SUCCEEDED
PENDING -> RUNNING -> PENDING
PENDING -> RUNNING -> DEAD_LETTERED
```

`FAILED` and `CANCELLED` are reserved for future operator workflows. A later
version could add a cancel endpoint or an explicit terminal failed state, but
this version keeps worker execution simple: retryable failures are requeued
with backoff, and exhausted or non-retryable failures are dead-lettered.

Recommended job fields:

```text
attempts          int, default 0
max_attempts      int, default 3
run_after         timestamptz, default now()
lease_expires_at  timestamptz, nullable
locked_by         text, nullable
lease_id          uuid, nullable
last_error        text, nullable
completed_at      timestamptz, nullable
```

Recommended tenant quota table:

```text
tenant_runtime_quotas
- tenant_id uuid primary key references tenants(id)
- running_jobs int not null default 0
- updated_at timestamptz not null default now()
```

Recommended DLQ table:

```text
dead_letter_jobs
- id uuid primary key
- job_id uuid not null unique references jobs(id)
- tenant_id uuid not null references tenants(id)
- payload jsonb not null
- final_error text not null
- attempts int not null
- dead_lettered_at timestamptz not null default now()
```

## Claim Flow

A job is eligible for execution when:

```text
status = 'PENDING'
run_after <= now()
```

The worker claim must happen in one database transaction:

1. Select an eligible job with `FOR UPDATE SKIP LOCKED`.
2. Ensure the tenant has available running-job capacity.
3. Increment the tenant's `running_jobs` counter.
4. Mark the job `RUNNING`.
5. Increment `attempts`.
6. Set `locked_by`, a fresh `lease_id`, and `lease_expires_at`.
7. Insert a `job_events` row.
8. Commit before running the handler.

The handler runs after commit so long-running work does not hold database locks.

Example claim query:

```sql
SELECT id, tenant_id, job_type, payload, attempts, max_attempts
FROM jobs
JOIN tenants ON tenants.id = jobs.tenant_id
LEFT JOIN tenant_runtime_quotas q ON q.tenant_id = jobs.tenant_id
WHERE status = 'PENDING'
  AND run_after <= now()
  AND COALESCE(q.running_jobs, 0) < tenants.max_running_jobs
ORDER BY priority DESC, created_at ASC
FOR UPDATE SKIP LOCKED
LIMIT 10;
```

Example quota reservation:

```sql
UPDATE tenant_runtime_quotas q
SET running_jobs = running_jobs + 1,
    updated_at = now()
FROM tenants t
WHERE q.tenant_id = t.id
  AND q.tenant_id = $1
  AND q.running_jobs < t.max_running_jobs;
```

Example lease update:

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

If the quota update affects no rows, the worker should skip that job and poll again. It should not mark the job failed just because its tenant is temporarily at capacity.

## Ack, Retry, And DLQ Flow

### Success

When a handler succeeds, the worker marks the job complete and releases the tenant slot in one transaction.

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

The `locked_by`, `lease_id`, and live `lease_expires_at` guards prevent stale workers from acking jobs they no longer own, even when worker IDs are reused.

### Retryable Failure

When a handler raises a retryable error and attempts remain, the worker returns the job to `PENDING`.

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

Backoff should be bounded:

```text
delay_seconds = min(max_backoff_seconds, base_backoff_seconds * 2 ^ (attempts - 1) + jitter)
```

Suggested defaults:

```text
base_backoff_seconds = 2
max_backoff_seconds = 300
jitter_seconds = 0..3
```

### Non-Retryable Or Exhausted Failure

When a handler raises a non-retryable error, or when `attempts >= max_attempts`, the worker marks the job `DEAD_LETTERED` and inserts a `dead_letter_jobs` row.

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

The worker preserves the original payload and final error in `dead_letter_jobs`.
Current DLQ visibility comes from `GET /jobs?status=DEAD_LETTERED`, job
details, job events, dashboard status filters, and Prometheus metrics. A
dedicated DLQ requeue API is intentionally left as future operator tooling.

## Lease Expiry Recovery

A lease is expired when:

```text
status = 'RUNNING'
lease_expires_at < now()
```

The lease reaper should process expired jobs in small batches using row locks:

```sql
SELECT id, tenant_id, attempts, max_attempts
FROM jobs
WHERE status = 'RUNNING'
  AND lease_expires_at < now()
ORDER BY lease_expires_at ASC
FOR UPDATE SKIP LOCKED
LIMIT $1;
```

For each expired job:

1. Release the tenant runtime quota.
2. If attempts remain, set status to `PENDING`, clear lease fields, set `run_after`, and record a timeout event.
3. If attempts are exhausted, set status to `DEAD_LETTERED`, clear lease fields, insert a DLQ row, and record a timeout event.

The reaper should be safe to run as a single process for the take-home. If multiple reapers run accidentally, `FOR UPDATE SKIP LOCKED` and idempotent DLQ inserts keep recovery safe.

## Configuration

Recommended environment variables:

```text
DATABASE_URL=postgresql+asyncpg://reach:reach@postgres:5432/reach
WORKER_POLL_INTERVAL_SECONDS=1
WORKER_LEASE_SECONDS=60
WORKER_BATCH_SIZE=10
WORKER_BASE_BACKOFF_SECONDS=2
WORKER_MAX_BACKOFF_SECONDS=300
LEASE_REAPER_INTERVAL_SECONDS=10
LEASE_REAPER_BATCH_SIZE=50
```

If `WORKER_ID` is not set, the process generates one from hostname, process ID, and a short random suffix. Only set `WORKER_ID` manually for single-process debugging; scaled workers should use generated or otherwise container-unique IDs. `WORKER_BATCH_SIZE` is the number of eligible claim candidates inspected per poll; each worker still executes one claimed job at a time.

## Proposed Code Structure

```text
backend/app
├── repositories
│   ├── jobs.py
│   └── worker_jobs.py
├── services
│   ├── job_execution.py
│   └── quotas.py
└── workers
    ├── __init__.py
    ├── worker.py
    ├── lease_reaper.py
    ├── handlers.py
    └── settings.py
```

Suggested ownership:

- `worker_jobs.py` contains claim, ack, retry, DLQ, and lease-recovery database operations.
- `quotas.py` contains tenant runtime quota reservation and release helpers.
- `handlers.py` contains the job-type registry and demonstration handlers.
- `worker.py` owns the polling loop and signal handling.
- `lease_reaper.py` owns expired lease recovery.
- `settings.py` owns worker-specific environment parsing.

## Docker Compose

The current `docker-compose.yml` runs the frontend, API server, Postgres, one worker process, and one lease reaper process. The worker services are defined as separate backend containers so they can be scaled independently from the API.

```yaml
worker:
  build:
    context: ./backend
  env_file:
    - path: ./backend/.env
      required: false
  environment:
    DATABASE_URL: postgresql+asyncpg://reach:reach@postgres:5432/reach
  depends_on:
    postgres:
      condition: service_healthy
    server:
      condition: service_healthy
  command: python -m app.workers.worker

lease-reaper:
  build:
    context: ./backend
  env_file:
    - path: ./backend/.env
      required: false
  environment:
    DATABASE_URL: postgresql+asyncpg://reach:reach@postgres:5432/reach
  depends_on:
    postgres:
      condition: service_healthy
    server:
      condition: service_healthy
  command: python -m app.workers.lease_reaper
```

Scale workers locally:

```bash
docker compose up --scale worker=4
```

Run one worker directly from the backend directory:

```bash
uv run python -m app.workers.worker
```

Run the lease reaper directly:

```bash
uv run python -m app.workers.lease_reaper
```

## Job Events

Workers should write events using the existing `job_events` table.

Recommended event types:

```text
CLAIMED
SUCCEEDED
FAILED_RETRY_SCHEDULED
DEAD_LETTERED
LEASE_EXPIRED
REQUEUED_FROM_TIMEOUT
```

Example event metadata:

```json
{
  "workerId": "worker-1",
  "attempt": 2,
  "leaseSeconds": 60,
  "backoffSeconds": 8,
  "errorType": "TimeoutError"
}
```

Events are part of the public job history, so they should be concise and avoid secrets from payloads or exception messages.

## Observability

Implemented worker logs are structured JSON records emitted through the Python
standard library logger. They include `traceId` and `requestId` when the job was
submitted through the API with trace metadata.

Minimum useful logs:

- worker started
- job claimed
- job succeeded
- job failed and scheduled for retry
- job moved to DLQ
- tenant quota reached
- lease expired and recovered
- worker shutdown requested

Worker claim, success, retry, DLQ, and lease-recovery events also persist the
submitted `requestId` and `traceId` in `job_events.metadata` when available.
That gives a reviewer a concrete correlation path from API submission to worker
execution without adding OpenTelemetry dependencies.

Implemented worker lifecycle metrics:

```text
jobs_claimed_total{tenant_id,worker_id}
jobs_succeeded_total{tenant_id,worker_id}
jobs_retried_total{tenant_id}
jobs_dead_lettered_total{tenant_id}
job_lease_expired_total{tenant_id}
queue_depth{tenant_id,status}
running_jobs{tenant_id}
dead_letter_jobs{tenant_id}
oldest_pending_age_seconds{tenant_id}
tenant_running_limit{tenant_id}
tenant_runtime_slots_used{tenant_id}
job_execution_duration_seconds_bucket{tenant_id,job_type,outcome}
job_queue_wait_seconds_bucket{tenant_id,job_type}
```

The API also refreshes database-backed queue gauges during `GET /metrics`, so
autoscaling and alerting can use authoritative queue depth and queue age rather
than dashboard samples.

The current implementation does not expose a standalone
`worker_available_capacity` metric. Capacity is derived from tenant runtime
quota gauges:

```text
available tenant slots =
  max(tenant_running_limit - tenant_runtime_slots_used, 0)
```

That is intentional for the take-home: each worker process handles one job at a
time, while tenant concurrency quotas are the control plane that prevents one
tenant from consuming all worker capacity. A production worker fleet could add
heartbeats and per-process capacity gauges later.

Example scaling policy for a real deployment:

```text
Scale out when:
- sum(queue_depth{status="PENDING"}) > 100 for 3 minutes, or
- max(oldest_pending_age_seconds) > 60 seconds, or
- avg(tenant_runtime_slots_used / tenant_running_limit) > 0.8.

Scale in when:
- sum(queue_depth{status="PENDING"}) < 10 for 10 minutes, and
- max(oldest_pending_age_seconds) < 10 seconds, and
- avg(tenant_runtime_slots_used / tenant_running_limit) < 0.3.
```

## Testing Strategy

Required worker tests:

- a worker claims a pending job and marks it `RUNNING`
- two workers cannot claim the same job concurrently
- a successful handler marks the job `SUCCEEDED`
- a retryable handler failure returns the job to `PENDING`
- backoff sets `run_after` in the future
- exhausted attempts move the job to `DEAD_LETTERED`
- DLQ insert is idempotent
- tenant runtime quota prevents over-claiming
- runtime quota is released on success
- runtime quota is released on retry
- runtime quota is released on DLQ
- expired leases are recovered by the lease reaper
- stale workers cannot ack jobs after lease recovery
- worker transitions write job events

Useful integration test:

1. Start Postgres and the API.
2. Submit several jobs through `POST /jobs`.
3. Start multiple workers.
4. Verify every job reaches `SUCCEEDED` or `DEAD_LETTERED`.
5. Verify no job is successfully claimed by more than one active lease at the same time.

## Implementation Notes

- The worker should commit the claim transaction before running the handler.
- Ack, retry, DLQ, and quota release should be one transaction.
- SQL updates should include `status = 'RUNNING'`, `locked_by = worker_id`, `lease_id`, and live `lease_expires_at` guards.
- The worker should trap `SIGINT` and `SIGTERM`, finish or fail the current database operation, and exit cleanly.
- Handlers should be idempotent because the platform provides at-least-once execution.
- Unknown `job_type` should be treated as non-retryable and moved to the DLQ.
- Payloads should not be logged wholesale unless they are known to be safe.
- The first version should process one job at a time per process; horizontal scaling comes from running more worker processes.
- Local horizontal scaling can be demonstrated with `docker compose up --scale worker=4`.
- Kubernetes/ECS autoscaling automation is out of scope; use `queue_depth`, `oldest_pending_age_seconds`, and `tenant_runtime_slots_used / tenant_running_limit` as the documented production scaling inputs.

## What This Leaves Out

The worker layer does not need to include:

- autoscaling automation
- a separate worker heartbeat or worker available-capacity metric
- worker heartbeats separate from lease expiry
- exactly-once side-effect guarantees
- OpenTelemetry export, a collector, or a trace backend
- priority starvation protection
- real external email or webhook integrations
- a DLQ requeue API

Those can be added after the core claim, execute, ack, retry, DLQ, and reaper semantics are correct.

## Implemented Worker Layer

The repository includes the worker layer described above:

1. Migrations add `DEAD_LETTERED`, worker lease fields, tenant runtime quotas, and `dead_letter_jobs`.
2. SQLAlchemy models include the worker queue columns and tables.
3. `app/repositories/worker_jobs.py` implements claim, ack, retry, DLQ, and lease recovery database operations.
4. `app/workers/handlers.py` provides deterministic demonstration handlers.
5. `python -m app.workers.worker` and `python -m app.workers.lease_reaper` are runnable entry points.
6. `docker-compose.yml` includes `worker` and `lease-reaper` services.
7. The pytest suite covers concurrent claims, retries, lease expiry, stale acks, quota release, DLQ behavior, and stress behavior across multiple workers.
