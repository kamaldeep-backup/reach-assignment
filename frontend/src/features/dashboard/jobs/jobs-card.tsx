import { ChevronLeftIcon, ChevronRightIcon, RefreshCwIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardAction,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import type { JobStatusStreamState } from "@/features/dashboard/use-job-status-stream"
import { JobsTable } from "@/features/dashboard/jobs/jobs-table"
import { JOB_STATUSES, type JobResponse, type JobStatusFilter } from "@/lib/jobs-api"

type JobsCardProps = {
  jobs: JobResponse[]
  isLoading: boolean
  isFetching: boolean
  page: number
  pageSize: number
  statusFilter: JobStatusFilter
  streamState: JobStatusStreamState
  totalJobs: number
  hasNextPage: boolean
  onPageChange: (page: number) => void
  onStatusFilterChange: (status: JobStatusFilter) => void
  onRefresh: () => void
  onSelectJob: (jobId: string) => void
}

const statusFilterOptions: Array<{ value: JobStatusFilter; label: string }> = [
  { value: "ALL", label: "All" },
  ...JOB_STATUSES.map((status) => ({
    value: status,
    label: status.replace("_", " "),
  })),
]

export function JobsCard({
  jobs,
  isLoading,
  isFetching,
  page,
  pageSize,
  statusFilter,
  streamState,
  totalJobs,
  hasNextPage,
  onPageChange,
  onStatusFilterChange,
  onRefresh,
  onSelectJob,
}: JobsCardProps) {
  const firstJobNumber = totalJobs === 0 ? 0 : (page - 1) * pageSize + 1
  const lastJobNumber = Math.min(page * pageSize, totalJobs)
  const totalPages = Math.max(1, Math.ceil(totalJobs / pageSize))

  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Jobs</CardTitle>
        <CardAction className="flex items-center gap-2">
          <Badge variant={streamState === "connected" ? "secondary" : "outline"}>
            {streamState === "connected" ? "Live" : "Connecting"}
          </Badge>
          <Button variant="outline" size="sm" onClick={onRefresh}>
            <RefreshCwIcon data-icon="inline-start" />
            Refresh
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <Tabs
          value={statusFilter}
          onValueChange={(value) =>
            onStatusFilterChange(value as JobStatusFilter)
          }
        >
          <TabsList className="max-w-full overflow-x-auto">
            {statusFilterOptions.map((option) => (
              <TabsTrigger key={option.value} value={option.value}>
                {option.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <JobsTable
          jobs={jobs}
          isLoading={isLoading}
          onSelectJob={onSelectJob}
        />
        <div className="flex flex-col gap-3 border-t pt-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="text-sm text-muted-foreground">
            {isFetching && !isLoading ? "Updating. " : null}
            Showing {firstJobNumber}-{lastJobNumber} of {totalJobs} jobs
          </div>
          <div className="flex items-center justify-between gap-3 sm:justify-end">
            <div className="text-sm text-muted-foreground">
              Page {page} of {totalPages}
            </div>
            <div className="flex items-center gap-1">
              <Button
                variant="outline"
                size="icon-sm"
                aria-label="Previous jobs page"
                title="Previous page"
                disabled={page <= 1}
                onClick={() => onPageChange(Math.max(1, page - 1))}
              >
                <ChevronLeftIcon />
              </Button>
              <Button
                variant="outline"
                size="icon-sm"
                aria-label="Next jobs page"
                title="Next page"
                disabled={!hasNextPage}
                onClick={() => onPageChange(page + 1)}
              >
                <ChevronRightIcon />
              </Button>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
