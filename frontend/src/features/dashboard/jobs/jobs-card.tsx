import { RefreshCwIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { JobsTable } from "@/features/dashboard/jobs/jobs-table"
import { JOB_STATUSES, type JobResponse, type JobStatusFilter } from "@/lib/jobs-api"

type JobsCardProps = {
  jobs: JobResponse[]
  isLoading: boolean
  statusFilter: JobStatusFilter
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
  statusFilter,
  onStatusFilterChange,
  onRefresh,
  onSelectJob,
}: JobsCardProps) {
  return (
    <Card className="min-w-0">
      <CardHeader>
        <CardTitle>Jobs</CardTitle>
        <CardDescription>
          Polls the backend jobs API every five seconds.
        </CardDescription>
        <CardAction>
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
      </CardContent>
    </Card>
  )
}
