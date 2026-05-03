import {
  API_PREFIX,
  API_ORIGIN,
  getBearerHeaders,
  readApiResponse,
} from "@/lib/api-client"

export const JOB_STATUSES = [
  "PENDING",
  "RUNNING",
  "SUCCEEDED",
  "FAILED",
  "DEAD_LETTERED",
  "CANCELLED",
] as const

export type JobStatus = (typeof JOB_STATUSES)[number]
export type JobStatusFilter = "ALL" | JobStatus

export type JobResponse = {
  jobId: string
  idempotencyKey: string
  type: string
  payload: Record<string, unknown>
  status: JobStatus
  priority: number
  attempts: number
  maxAttempts: number
  runAfter: string
  leaseExpiresAt: string | null
  lockedBy: string | null
  lastError: string | null
  createdAt: string
  updatedAt: string
  completedAt: string | null
}

export type JobListResponse = {
  items: JobResponse[]
  total: number
  limit: number
  offset: number
  hasMore: boolean
}

export type MetricsSummaryResponse = {
  pending: number
  running: number
  succeeded: number
  failed: number
  deadLettered: number
  queueDepth: number
  oldestPendingAgeSeconds: number
  runningLimit: number
}

export type JobEventResponse = {
  eventId: string
  jobId: string
  eventType: string
  fromStatus: JobStatus | null
  toStatus: JobStatus | null
  message: string | null
  metadata: Record<string, unknown>
  createdAt: string
}

export type JobStreamMessage =
  | {
      type: "connected" | "pong"
    }
  | {
      type: "job.event"
      job: JobResponse
      event: JobEventResponse
    }

export type JobCreateRequest = {
  type: string
  payload: Record<string, unknown>
  priority: number
}

export async function listJobs({
  token,
  status,
  limit = 50,
  offset = 0,
}: {
  token: string
  status: JobStatusFilter
  limit?: number
  offset?: number
}) {
  const params = new URLSearchParams()
  params.set("limit", String(limit))
  params.set("offset", String(offset))

  if (status !== "ALL") {
    params.set("status", status)
  }

  const response = await fetch(`${API_PREFIX}/jobs?${params.toString()}`, {
    headers: getBearerHeaders(token),
  })

  return readApiResponse<JobListResponse>(response)
}

export async function getMetricsSummary(token: string) {
  const response = await fetch(`${API_PREFIX}/metrics/summary`, {
    headers: getBearerHeaders(token),
  })

  return readApiResponse<MetricsSummaryResponse>(response)
}

export async function createJob({
  token,
  idempotencyKey,
  payload,
}: {
  token: string
  idempotencyKey: string
  payload: JobCreateRequest
}) {
  const response = await fetch(`${API_PREFIX}/jobs`, {
    method: "POST",
    headers: {
      ...getBearerHeaders(token),
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify(payload),
  })

  return readApiResponse<JobResponse>(response)
}

export async function listJobEvents({
  token,
  jobId,
}: {
  token: string
  jobId: string
}) {
  const response = await fetch(`${API_PREFIX}/jobs/${jobId}/events`, {
    headers: getBearerHeaders(token),
  })

  return readApiResponse<JobEventResponse[]>(response)
}

export function getJobsStreamUrl(token: string) {
  const url = new URL(`${API_ORIGIN}/api/v1/jobs/stream`)
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:"
  url.searchParams.set("token", token)
  return url.toString()
}
