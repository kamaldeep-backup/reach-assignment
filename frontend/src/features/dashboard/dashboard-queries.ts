import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"

import {
  createApiKey,
  listApiKeys,
  revokeApiKey,
  type APIKeyCreateRequest,
} from "@/lib/api-keys-api"
import {
  createJob,
  getMetricsSummary,
  listJobEvents,
  listJobs,
  type JobCreateRequest,
  type JobStatusFilter,
} from "@/lib/jobs-api"

export const jobsQueryKey = ["jobs"] as const
export const apiKeysQueryKey = ["api-keys"] as const
export const JOBS_PAGE_SIZE = 10
export const metricsSummaryQueryKey = [...jobsQueryKey, "metrics-summary"] as const

export function useDashboardData({
  token,
  statusFilter,
  jobsPage,
  selectedJobId,
}: {
  token: string
  statusFilter: JobStatusFilter
  jobsPage: number
  selectedJobId: string | null
}) {
  const queryClient = useQueryClient()
  const jobsOffset = (jobsPage - 1) * JOBS_PAGE_SIZE

  const jobsQuery = useQuery({
    queryKey: [...jobsQueryKey, statusFilter, jobsPage, JOBS_PAGE_SIZE],
    queryFn: () =>
      listJobs({
        token,
        status: statusFilter,
        limit: JOBS_PAGE_SIZE,
        offset: jobsOffset,
      }),
    placeholderData: keepPreviousData,
  })

  const metricsSummaryQuery = useQuery({
    queryKey: metricsSummaryQueryKey,
    queryFn: () => getMetricsSummary(token),
  })

  const apiKeysQuery = useQuery({
    queryKey: apiKeysQueryKey,
    queryFn: () => listApiKeys(token),
  })

  const jobEventsQuery = useQuery({
    queryKey: [...jobsQueryKey, selectedJobId, "events"],
    queryFn: () => listJobEvents({ token, jobId: selectedJobId ?? "" }),
    enabled: selectedJobId !== null,
  })

  const createJobMutation = useMutation({
    mutationFn: ({
      idempotencyKey,
      payload,
    }: {
      idempotencyKey: string
      payload: JobCreateRequest
    }) => createJob({ token, idempotencyKey, payload }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: jobsQueryKey })
    },
  })

  const createApiKeyMutation = useMutation({
    mutationFn: (payload: APIKeyCreateRequest) => createApiKey({ token, payload }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: apiKeysQueryKey })
    },
  })

  const revokeApiKeyMutation = useMutation({
    mutationFn: (apiKeyId: string) => revokeApiKey({ token, apiKeyId }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: apiKeysQueryKey })
    },
  })

  return {
    apiKeysQuery,
    createApiKeyMutation,
    createJobMutation,
    jobEventsQuery,
    jobsQuery,
    metricsSummaryQuery,
    revokeApiKeyMutation,
  }
}
