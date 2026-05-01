import { ClockIcon, EyeIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { formatDate } from "@/features/dashboard/dashboard-utils"
import { JobStatusBadge } from "@/features/dashboard/jobs/job-status-badge"
import type { JobResponse } from "@/lib/jobs-api"

type JobsTableProps = {
  jobs: JobResponse[]
  isLoading: boolean
  onSelectJob: (jobId: string) => void
}

export function JobsTable({ jobs, isLoading, onSelectJob }: JobsTableProps) {
  if (isLoading) {
    return (
      <div className="flex min-h-48 items-center justify-center gap-2 text-sm text-muted-foreground">
        <Spinner />
        Loading jobs
      </div>
    )
  }

  if (jobs.length === 0) {
    return (
      <div className="flex min-h-48 flex-col items-center justify-center gap-2 text-center">
        <ClockIcon className="size-5 text-muted-foreground" aria-hidden="true" />
        <div className="font-medium">No jobs match this filter</div>
        <p className="max-w-sm text-sm text-muted-foreground">
          Submit a job or switch filters to inspect previous queue activity.
        </p>
      </div>
    )
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Job</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Priority</TableHead>
          <TableHead>Attempts</TableHead>
          <TableHead>Updated</TableHead>
          <TableHead className="text-right">Action</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {jobs.map((job) => (
          <TableRow key={job.jobId}>
            <TableCell>
              <div className="flex max-w-56 flex-col gap-1">
                <span className="truncate font-medium">{job.type}</span>
                <span className="truncate text-xs text-muted-foreground">
                  {job.jobId}
                </span>
              </div>
            </TableCell>
            <TableCell>
              <JobStatusBadge status={job.status} />
            </TableCell>
            <TableCell>{job.priority}</TableCell>
            <TableCell>
              {job.attempts} / {job.maxAttempts}
            </TableCell>
            <TableCell>{formatDate(job.updatedAt)}</TableCell>
            <TableCell className="text-right">
              <Button
                variant="outline"
                size="sm"
                onClick={() => onSelectJob(job.jobId)}
              >
                <EyeIcon data-icon="inline-start" />
                Details
              </Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
