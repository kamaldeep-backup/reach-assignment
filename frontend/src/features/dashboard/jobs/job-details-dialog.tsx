import { TriangleAlertIcon } from "lucide-react"
import type { ReactNode } from "react"

import { Alert, AlertDescription } from "@/components/ui/alert"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { FieldTitle } from "@/components/ui/field"
import { Separator } from "@/components/ui/separator"
import { Spinner } from "@/components/ui/spinner"
import { formatDate } from "@/features/dashboard/dashboard-utils"
import { JobStatusBadge } from "@/features/dashboard/jobs/job-status-badge"
import type { JobEventResponse, JobResponse } from "@/lib/jobs-api"

type JobDetailsDialogProps = {
  job?: JobResponse
  events: JobEventResponse[]
  isEventsLoading: boolean
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function JobDetailsDialog({
  job,
  events,
  isEventsLoading,
  open,
  onOpenChange,
}: JobDetailsDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Job details</DialogTitle>
          <DialogDescription>
            Status, worker lease metadata, payload, and event history.
          </DialogDescription>
        </DialogHeader>

        {job ? (
          <div className="flex max-h-[70svh] flex-col gap-4 overflow-y-auto pr-1">
            <div className="grid gap-3 sm:grid-cols-2">
              <Detail label="Job ID" value={job.jobId} />
              <Detail label="Idempotency" value={job.idempotencyKey} />
              <Detail label="Type" value={job.type} />
              <Detail
                label="Status"
                value={<JobStatusBadge status={job.status} />}
              />
              <Detail
                label="Attempts"
                value={`${job.attempts} / ${job.maxAttempts}`}
              />
              <Detail label="Priority" value={String(job.priority)} />
              <Detail label="Run after" value={formatDate(job.runAfter)} />
              <Detail
                label="Lease expires"
                value={formatDate(job.leaseExpiresAt)}
              />
              <Detail label="Locked by" value={job.lockedBy ?? "Unassigned"} />
              <Detail label="Completed" value={formatDate(job.completedAt)} />
            </div>

            {job.lastError ? (
              <Alert variant="destructive">
                <TriangleAlertIcon />
                <AlertDescription>{job.lastError}</AlertDescription>
              </Alert>
            ) : null}

            <div className="flex flex-col gap-2">
              <FieldTitle>Payload</FieldTitle>
              <pre className="max-h-56 overflow-auto rounded-lg border bg-muted/40 p-3 text-xs">
                {JSON.stringify(job.payload, null, 2)}
              </pre>
            </div>

            <Separator />

            <div className="flex flex-col gap-3">
              <FieldTitle>Events</FieldTitle>
              {isEventsLoading ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Spinner />
                  Loading events
                </div>
              ) : events.length === 0 ? (
                <div className="text-sm text-muted-foreground">
                  No events recorded for this job.
                </div>
              ) : (
                events.map((event) => (
                  <div key={event.eventId} className="rounded-lg border p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="font-medium">{event.eventType}</div>
                      <div className="text-xs text-muted-foreground">
                        {formatDate(event.createdAt)}
                      </div>
                    </div>
                    <div className="mt-1 text-sm text-muted-foreground">
                      {event.fromStatus ?? "none"} to {event.toStatus ?? "none"}
                    </div>
                    {event.message ? (
                      <div className="mt-2 text-sm">{event.message}</div>
                    ) : null}
                  </div>
                ))
              )}
            </div>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

function Detail({ label, value }: { label: string; value: string | ReactNode }) {
  return (
    <div className="min-w-0 rounded-lg border p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 truncate text-sm font-medium">{value}</div>
    </div>
  )
}
