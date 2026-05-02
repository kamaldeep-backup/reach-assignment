import {
  ActivityIcon,
  AlertCircleIcon,
  Building2Icon,
  CalendarIcon,
  CheckCircle2Icon,
  ClockIcon,
  KeyRoundIcon,
  LayoutDashboardIcon,
  LoaderCircleIcon,
  LogOutIcon,
  MailIcon,
  MenuIcon,
  ShieldCheckIcon,
  UserCircleIcon,
  XCircleIcon,
  type LucideIcon,
} from "lucide-react"
import { useMemo, useState } from "react"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
} from "@/components/ui/dialog"
import { ApiKeysCard } from "@/features/dashboard/api-keys/api-keys-card"
import { RevealedApiKeyDialog } from "@/features/dashboard/api-keys/revealed-api-key-dialog"
import {
  DashboardMetrics,
  type Metric,
} from "@/features/dashboard/components/dashboard-metrics"
import { WorkspaceLimitsCard } from "@/features/dashboard/components/workspace-limits-card"
import {
  JOBS_PAGE_SIZE,
  useDashboardData,
} from "@/features/dashboard/dashboard-queries"
import { formatDate, getJobCounts } from "@/features/dashboard/dashboard-utils"
import { JobDetailsDialog } from "@/features/dashboard/jobs/job-details-dialog"
import { JobSubmitCard } from "@/features/dashboard/jobs/job-submit-card"
import { JobsCard } from "@/features/dashboard/jobs/jobs-card"
import { useJobStatusStream } from "@/features/dashboard/use-job-status-stream"
import { getErrorMessage } from "@/lib/api-client"
import type { CurrentUserResponse } from "@/lib/auth-api"
import type { JobStatusFilter } from "@/lib/jobs-api"
import { cn } from "@/lib/utils"

type DashboardScreenProps = {
  currentUser?: CurrentUserResponse
  error: unknown
  isLoading: boolean
  onLogout: () => void
  token: string
}

type DashboardPage = "jobs" | "api-keys" | "limits" | "profile"

const dashboardPages: Array<{
  id: DashboardPage
  label: string
  description: string
  icon: LucideIcon
}> = [
  {
    id: "jobs",
    label: "Jobs",
    description: "Queue activity and job submission",
    icon: LayoutDashboardIcon,
  },
  {
    id: "api-keys",
    label: "API Keys",
    description: "Tenant access credentials",
    icon: KeyRoundIcon,
  },
  {
    id: "limits",
    label: "Workspace Limits",
    description: "Tenant guardrails and capacity",
    icon: ActivityIcon,
  },
  {
    id: "profile",
    label: "Profile",
    description: "Account and workspace settings",
    icon: UserCircleIcon,
  },
]

export function DashboardScreen({
  currentUser,
  error,
  isLoading,
  onLogout,
  token,
}: DashboardScreenProps) {
  const [activePage, setActivePage] = useState<DashboardPage>("jobs")
  const [statusFilter, setStatusFilter] = useState<JobStatusFilter>("ALL")
  const [jobsPage, setJobsPage] = useState(1)
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)
  const [copiedValue, setCopiedValue] = useState<string | null>(null)
  const [isCreateJobOpen, setIsCreateJobOpen] = useState(false)
  const [isMobileNavOpen, setIsMobileNavOpen] = useState(false)
  const jobStatusStreamState = useJobStatusStream({ token })

  const {
    apiKeysQuery,
    createApiKeyMutation,
    createJobMutation,
    jobEventsQuery,
    jobsQuery,
    overviewJobsQuery,
    revokeApiKeyMutation,
  } = useDashboardData({ token, statusFilter, jobsPage, selectedJobId })

  const jobs = useMemo(() => jobsQuery.data?.items ?? [], [jobsQuery.data])
  const jobsTotal = jobsQuery.data?.total ?? 0
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

  const activePageConfig =
    dashboardPages.find((page) => page.id === activePage) ?? dashboardPages[0]

  return (
    <div className="min-h-svh bg-muted/30">
      <div className="flex min-h-svh">
        <DashboardSidebar
          activePage={activePage}
          className="hidden md:flex"
          currentUser={currentUser}
          isLoading={isLoading}
          onPageChange={setActivePage}
        />

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="border-b bg-background/95 px-4 py-4 md:px-6">
            <div className="flex items-center gap-3">
              <Button
                variant="outline"
                size="icon"
                className="md:hidden"
                aria-label="Open navigation"
                title="Open navigation"
                onClick={() => setIsMobileNavOpen(true)}
              >
                <MenuIcon />
              </Button>
              <div className="flex min-w-0 flex-col gap-1">
                <h1 className="truncate font-heading text-xl font-medium tracking-tight">
                  {activePageConfig.label}
                </h1>
                <p className="truncate text-sm text-muted-foreground">
                  {activePageConfig.description}
                </p>
              </div>
            </div>
          </header>

          <main className="flex-1 p-4 md:p-6">
            <div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
              {error ? (
                <Alert variant="destructive">
                  <AlertCircleIcon />
                  <AlertDescription>{getErrorMessage(error)}</AlertDescription>
                </Alert>
              ) : null}

              {activePage === "jobs" ? (
                <section className="flex min-w-0 flex-col gap-6">
                  <DashboardMetrics metrics={metrics} />

                  <JobsCard
                    jobs={jobs}
                    isLoading={jobsQuery.isLoading}
                    isFetching={jobsQuery.isFetching}
                    page={jobsPage}
                    pageSize={JOBS_PAGE_SIZE}
                    statusFilter={statusFilter}
                    streamState={jobStatusStreamState}
                    totalJobs={jobsTotal}
                    hasNextPage={jobsQuery.data?.hasMore ?? false}
                    onCreateJob={() => setIsCreateJobOpen(true)}
                    onPageChange={setJobsPage}
                    onStatusFilterChange={(nextStatusFilter) => {
                      setStatusFilter(nextStatusFilter)
                      setJobsPage(1)
                    }}
                    onRefresh={() => {
                      void jobsQuery.refetch()
                      void overviewJobsQuery.refetch()
                    }}
                    onSelectJob={setSelectedJobId}
                  />
                </section>
              ) : null}

              {activePage === "api-keys" ? (
                <section className="max-w-4xl">
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
                </section>
              ) : null}

              {activePage === "limits" ? (
                <section className="max-w-4xl">
                  <WorkspaceLimitsCard
                    activeKeys={activeKeys}
                    currentUser={currentUser}
                  />
                </section>
              ) : null}

              {activePage === "profile" ? (
                <ProfilePage
                  activeKeys={activeKeys}
                  currentUser={currentUser}
                  isLoading={isLoading}
                  onLogout={onLogout}
                />
              ) : null}
            </div>
          </main>
        </div>
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

      <Dialog open={isCreateJobOpen} onOpenChange={setIsCreateJobOpen}>
        <DialogContent className="max-h-[calc(100svh-2rem)] overflow-y-auto sm:max-w-2xl">
          <JobSubmitCard
            isPending={createJobMutation.isPending}
            error={createJobMutation.error}
            onSubmit={({ idempotencyKey, type, priority, payload }) =>
              createJobMutation.mutate(
                {
                  idempotencyKey,
                  payload: { type, priority, payload },
                },
                {
                  onSuccess: () => setIsCreateJobOpen(false),
                }
              )
            }
          />
        </DialogContent>
      </Dialog>

      <Dialog open={isMobileNavOpen} onOpenChange={setIsMobileNavOpen}>
        <DialogContent
          className="top-0 left-0 h-svh max-h-svh w-72 max-w-[85vw] translate-x-0 translate-y-0 overflow-hidden rounded-none p-0 sm:max-w-72"
          showCloseButton={false}
        >
          <DashboardSidebar
            activePage={activePage}
            className="h-full w-full border-r-0"
            currentUser={currentUser}
            isLoading={isLoading}
            onPageChange={(page) => {
              setActivePage(page)
              setIsMobileNavOpen(false)
            }}
          />
        </DialogContent>
      </Dialog>
    </div>
  )
}

function DashboardSidebar({
  activePage,
  className,
  currentUser,
  isLoading,
  onPageChange,
}: {
  activePage: DashboardPage
  className?: string
  currentUser?: CurrentUserResponse
  isLoading: boolean
  onPageChange: (page: DashboardPage) => void
}) {
  return (
    <aside
      className={cn(
        "sticky top-0 flex h-svh w-72 shrink-0 flex-col border-r bg-sidebar px-4 py-4 text-sidebar-foreground",
        className
      )}
    >
      <div className="flex items-center gap-3 px-1">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-sidebar-primary text-sm font-medium text-sidebar-primary-foreground">
          R
        </div>
        <div className="min-w-0">
          <div className="truncate font-heading text-base font-medium">
            {currentUser?.tenant.name ?? "Reach"}
          </div>
          <div className="truncate text-xs text-sidebar-foreground/60">
            {isLoading ? "Loading workspace" : currentUser?.email}
          </div>
        </div>
      </div>

      <nav className="mt-8 flex flex-col gap-1">
        {dashboardPages.map((page) => {
          const Icon = page.icon
          const isActive = activePage === page.id

          return (
            <Button
              key={page.id}
              variant="ghost"
              className={cn(
                "h-10 justify-start gap-3 px-3 text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                isActive &&
                  "bg-sidebar-accent text-sidebar-accent-foreground ring-1 ring-sidebar-border"
              )}
              aria-current={isActive ? "page" : undefined}
              title={page.label}
              onClick={() => onPageChange(page.id)}
            >
              <Icon className="size-4" aria-hidden="true" />
              <span>{page.label}</span>
            </Button>
          )
        })}
      </nav>
    </aside>
  )
}

function ProfilePage({
  activeKeys,
  currentUser,
  isLoading,
  onLogout,
}: {
  activeKeys: number
  currentUser?: CurrentUserResponse
  isLoading: boolean
  onLogout: () => void
}) {
  return (
    <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
      <Card>
        <CardHeader>
          <CardTitle>Account</CardTitle>
          <CardDescription>
            {isLoading ? "Loading account details" : currentUser?.email}
          </CardDescription>
          <CardAction>
            <Button variant="outline" onClick={onLogout}>
              <LogOutIcon data-icon="inline-start" />
              Logout
            </Button>
          </CardAction>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2">
          <ProfileField
            icon={MailIcon}
            label="Email"
            value={currentUser?.email ?? "Loading"}
          />
          <ProfileField
            icon={ShieldCheckIcon}
            label="Status"
            value={
              currentUser ? (currentUser.isActive ? "Active" : "Inactive") : "Loading"
            }
          />
          <ProfileField
            icon={CalendarIcon}
            label="Created"
            value={formatDate(currentUser?.createdAt)}
          />
          <ProfileField
            icon={UserCircleIcon}
            label="User ID"
            value={currentUser?.userId ?? "Loading"}
          />
        </CardContent>
      </Card>

      <div className="flex flex-col gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Tenant</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <ProfileField
              icon={Building2Icon}
              label="Workspace"
              value={currentUser?.tenant.name ?? "Loading"}
            />
            <ProfileField
              icon={ShieldCheckIcon}
              label="Role"
              value={currentUser?.tenant.role ?? "Loading"}
            />
            <div className="flex items-center justify-between rounded-lg border p-3">
              <span className="text-sm text-muted-foreground">
                Active API keys
              </span>
              <Badge variant="secondary">{activeKeys}</Badge>
            </div>
          </CardContent>
        </Card>

      </div>
    </section>
  )
}

function ProfileField({
  icon: Icon,
  label,
  value,
}: {
  icon: LucideIcon
  label: string
  value: string
}) {
  return (
    <div className="flex min-w-0 items-center gap-3 rounded-lg border p-3">
      <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted">
        <Icon className="size-4 text-muted-foreground" aria-hidden="true" />
      </div>
      <div className="min-w-0">
        <div className="truncate text-sm font-medium">{value}</div>
        <div className="truncate text-xs text-muted-foreground">{label}</div>
      </div>
    </div>
  )
}
