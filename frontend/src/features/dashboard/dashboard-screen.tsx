import {
  AlertCircleIcon,
  CheckCircle2Icon,
  ClockIcon,
  LoaderCircleIcon,
  XCircleIcon,
} from "lucide-react"
import { useMemo, useState } from "react"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { ApiKeysCard } from "@/features/dashboard/api-keys/api-keys-card"
import { RevealedApiKeyDialog } from "@/features/dashboard/api-keys/revealed-api-key-dialog"
import { DashboardHeader } from "@/features/dashboard/components/dashboard-header"
import {
  DashboardMetrics,
  type Metric,
} from "@/features/dashboard/components/dashboard-metrics"
import { WorkspaceLimitsCard } from "@/features/dashboard/components/workspace-limits-card"
import { useDashboardData } from "@/features/dashboard/dashboard-queries"
import { getJobCounts } from "@/features/dashboard/dashboard-utils"
import { JobDetailsDialog } from "@/features/dashboard/jobs/job-details-dialog"
import { JobSubmitCard } from "@/features/dashboard/jobs/job-submit-card"
import { JobsCard } from "@/features/dashboard/jobs/jobs-card"
import { getErrorMessage } from "@/lib/api-client"
import type { CurrentUserResponse } from "@/lib/auth-api"
import type { JobStatusFilter } from "@/lib/jobs-api"

type DashboardScreenProps = {
  currentUser?: CurrentUserResponse
  error: unknown
  isLoading: boolean
  onLogout: () => void
  token: string
}

export function DashboardScreen({
  currentUser,
  error,
  isLoading,
  onLogout,
  token,
}: DashboardScreenProps) {
  const [statusFilter, setStatusFilter] = useState<JobStatusFilter>("ALL")
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)
  const [copiedValue, setCopiedValue] = useState<string | null>(null)

  const {
    apiKeysQuery,
    createApiKeyMutation,
    createJobMutation,
    jobEventsQuery,
    jobsQuery,
    overviewJobsQuery,
    revokeApiKeyMutation,
  } = useDashboardData({ token, statusFilter, selectedJobId })

  const jobs = useMemo(() => jobsQuery.data?.items ?? [], [jobsQuery.data])
  const overviewJobs = useMemo(
    () => overviewJobsQuery.data?.items ?? [],
    [overviewJobsQuery.data]
  )
  const selectedJob = jobs.find((job) => job.jobId === selectedJobId)
  const activeKeys = apiKeysQuery.data?.filter((key) => key.isActive).length ?? 0

  const metrics = useMemo<Metric[]>(() => {
    const counts = getJobCounts(overviewJobs)
    const runningLimit = currentUser?.tenant.maxRunningJobs ?? 0

    return [
      {
        label: "Queue depth",
        value: String(counts.PENDING),
        detail: "Pending jobs",
        icon: ClockIcon,
      },
      {
        label: "Running",
        value: `${counts.RUNNING}/${runningLimit}`,
        detail: "Tenant concurrency",
        icon: LoaderCircleIcon,
      },
      {
        label: "Completed",
        value: String(counts.SUCCEEDED),
        detail: "Succeeded jobs",
        icon: CheckCircle2Icon,
      },
      {
        label: "Failures",
        value: String(counts.FAILED + counts.DEAD_LETTERED),
        detail: "Failed or DLQ",
        icon: XCircleIcon,
      },
    ]
  }, [currentUser?.tenant.maxRunningJobs, overviewJobs])

  const copyText = (value: string) => {
    void navigator.clipboard.writeText(value).then(() => {
      setCopiedValue(value)
    })
  }

  return (
    <main className="min-h-svh bg-background">
      <DashboardHeader
        currentUser={currentUser}
        isLoading={isLoading}
        onLogout={onLogout}
      />

      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 p-4 md:p-6">
        {error ? (
          <Alert variant="destructive">
            <AlertCircleIcon />
            <AlertDescription>{getErrorMessage(error)}</AlertDescription>
          </Alert>
        ) : null}

        <DashboardMetrics metrics={metrics} />

        <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]">
          <div className="flex min-w-0 flex-col gap-6">
            <WorkspaceLimitsCard
              activeKeys={activeKeys}
              currentUser={currentUser}
            />

            <JobsCard
              jobs={jobs}
              isLoading={jobsQuery.isLoading}
              statusFilter={statusFilter}
              onStatusFilterChange={setStatusFilter}
              onRefresh={() => {
                void jobsQuery.refetch()
                void overviewJobsQuery.refetch()
              }}
              onSelectJob={setSelectedJobId}
            />
          </div>

          <div className="flex flex-col gap-6">
            <JobSubmitCard
              isPending={createJobMutation.isPending}
              error={createJobMutation.error}
              onSubmit={({ idempotencyKey, type, priority, payload }) =>
                createJobMutation.mutate({
                  idempotencyKey,
                  payload: { type, priority, payload },
                })
              }
            />

            <ApiKeysCard
              keys={apiKeysQuery.data ?? []}
              isLoading={apiKeysQuery.isLoading}
              createError={createApiKeyMutation.error}
              revokeError={revokeApiKeyMutation.error}
              isCreating={createApiKeyMutation.isPending}
              isRevoking={revokeApiKeyMutation.isPending}
              onCreate={createApiKeyMutation.mutate}
              onRevoke={revokeApiKeyMutation.mutate}
            />
          </div>
        </section>
      </div>

      <JobDetailsDialog
        job={selectedJob}
        events={jobEventsQuery.data ?? []}
        isEventsLoading={jobEventsQuery.isLoading}
        open={selectedJobId !== null}
        onOpenChange={(open) => {
          if (!open) {
            setSelectedJobId(null)
          }
        }}
      />

      <RevealedApiKeyDialog
        value={createApiKeyMutation.data?.apiKey}
        copiedValue={copiedValue}
        onCopy={copyText}
        onClose={() => {
          setCopiedValue(null)
          createApiKeyMutation.reset()
        }}
      />
    </main>
  )
}
