# Worker Processing Layer

This document outlines the worker side of the take-home project. It describes the next layer after the baseline CRUD server in `CRUD_SERVER.md`: raw Python worker processes that claim pending jobs from Postgres, execute handlers asynchronously from the API request path, acknowledge successful work, retry transient failures, recover expired leases, and preserve terminal failures in a dead-letter queue.

The current repository implements the API, authentication, durable job submission, and job history. Worker code is not present yet. This document defines the worker design that should be added to evolve the baseline server toward the full platform described in `ARCHITECTURE.md`.

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
- set `locked_by` to the worker ID
- set `lease_expires_at`
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

Recommended job fields:

```text
attempts          int, default 0
max_attempts      int, default 3
run_after         timestamptz, default now()
lease_expires_at  timestamptz, nullable
locked_by         text, nullable
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
6. Set `locked_by` and `lease_expires_at`.
7. Insert a `job_events` row.
8. Commit before running the handler.

The handler runs after commit so long-running work does not hold database locks.

Example claim query:

```sql
SELECT id, tenant_id, job_type, payload, attempts, max_attempts
FROM jobs
WHERE status = 'PENDING'
  AND run_after <= now()
ORDER BY priority DESC, created_at ASC
FOR UPDATE SKIP LOCKED
LIMIT 1;
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
    lease_expires_at = now() + ($2 || ' seconds')::interval,
    updated_at = now()
WHERE id = $3
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
    completed_at = now(),
    updated_at = now()
WHERE id = $1
  AND status = 'RUNNING'
  AND locked_by = $2;
```

The `locked_by` guard prevents stale workers from acking jobs they no longer own.

### Retryable Failure

When a handler raises a retryable error and attempts remain, the worker returns the job to `PENDING`.

```sql
UPDATE jobs
SET status = 'PENDING',
    run_after = now() + ($1 || ' seconds')::interval,
    lease_expires_at = NULL,
    locked_by = NULL,
    last_error = $2,
    updated_at = now()
WHERE id = $3
  AND status = 'RUNNING'
  AND locked_by = $4;
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
    last_error = $1,
    completed_at = now(),
    updated_at = now()
WHERE id = $2
  AND status = 'RUNNING'
  AND locked_by = $3;
```

```sql
INSERT INTO dead_letter_jobs (job_id, tenant_id, payload, final_error, attempts)
SELECT id, tenant_id, payload, last_error, attempts
FROM jobs
WHERE id = $1
ON CONFLICT (job_id) DO NOTHING;
```

The worker should preserve the original payload and final error so operators can inspect or requeue the failed job later.

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
WORKER_ID=worker-local
WORKER_POLL_INTERVAL_SECONDS=1
WORKER_LEASE_SECONDS=60
WORKER_BATCH_SIZE=1
WORKER_BASE_BACKOFF_SECONDS=2
WORKER_MAX_BACKOFF_SECONDS=300
LEASE_REAPER_INTERVAL_SECONDS=10
LEASE_REAPER_BATCH_SIZE=50
```

If `WORKER_ID` is not set, the process can generate one from hostname, process ID, and a short random suffix.

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

The current `docker-compose.yml` runs the frontend, API server, and Postgres. The worker layer should add two backend services.

```yaml
worker:
  build:
    context: ./backend
  env_file:
    - path: ./backend/.env
      required: false
  environment:
    DATABASE_URL: postgresql+asyncpg://reach:reach@postgres:5432/reach
    WORKER_ID: worker-1
  depends_on:
    postgres:
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

Minimum useful logs:

- worker started
- job claimed
- job succeeded
- job failed and scheduled for retry
- job moved to DLQ
- tenant quota reached
- lease expired and recovered
- worker shutdown requested

Suggested metrics:

```text
worker_jobs_claimed_total
worker_jobs_succeeded_total
worker_jobs_failed_total
worker_jobs_retried_total
worker_jobs_dead_lettered_total
worker_claim_empty_total
worker_quota_blocked_total
worker_lease_expired_total
worker_job_duration_seconds
worker_job_queue_latency_seconds
```

For the take-home, structured logs and tests are enough. Prometheus metrics can be added later through the observability layer described in `ARCHITECTURE.md`.

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
- SQL updates should include `status = 'RUNNING'` and `locked_by = worker_id` guards.
- The worker should trap `SIGINT` and `SIGTERM`, finish or fail the current database operation, and exit cleanly.
- Handlers should be idempotent because the platform provides at-least-once execution.
- Unknown `job_type` should be treated as non-retryable and moved to the DLQ.
- Payloads should not be logged wholesale unless they are known to be safe.
- The first version should process one job at a time per process; horizontal scaling comes from running more worker processes.

## What This Leaves Out

The worker layer does not need to include:

- autoscaling automation
- worker heartbeats separate from lease expiry
- exactly-once side-effect guarantees
- distributed tracing in the first pass
- priority starvation protection
- real external email or webhook integrations
- a DLQ requeue API

Those can be added after the core claim, execute, ack, retry, DLQ, and reaper semantics are correct.

## Path From Baseline API To Workers

The current codebase can evolve toward this design by adding:

1. A migration for `DEAD_LETTERED`, worker lease fields, tenant runtime quotas, and `dead_letter_jobs`.
2. SQLAlchemy model updates for the new columns and tables.
3. Worker repository functions for claim, ack, retry, DLQ, and lease recovery.
4. A small handler registry with deterministic test handlers.
5. `python -m app.workers.worker` and `python -m app.workers.lease_reaper` entry points.
6. Docker Compose services for `worker` and `lease-reaper`.
7. Worker tests that cover concurrency, retries, lease expiry, stale acks, and DLQ behavior.
