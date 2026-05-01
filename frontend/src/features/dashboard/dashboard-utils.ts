import { JOB_STATUSES, type JobResponse, type JobStatus } from "@/lib/jobs-api"

export const samplePayload = JSON.stringify(
  {
    to: "customer@example.com",
    template: "welcome",
  },
  null,
  2
)

const dateFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
})

export function formatDate(value: string | null | undefined) {
  if (!value) {
    return "Never"
  }

  return dateFormatter.format(new Date(value))
}

export function makeIdempotencyKey() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `dashboard-${crypto.randomUUID()}`
  }

  return `dashboard-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function getJobCounts(jobs: JobResponse[]) {
  const counts = Object.fromEntries(
    JOB_STATUSES.map((status) => [status, 0])
  ) as Record<JobStatus, number>

  for (const job of jobs) {
    counts[job.status] += 1
  }

  return counts
}
