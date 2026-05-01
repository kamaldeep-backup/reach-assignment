import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import {
  createApiKey,
  listApiKeys,
  revokeApiKey,
  type APIKeyCreateRequest,
} from "@/lib/api-keys-api"
import {
  createJob,
  listJobEvents,
  listJobs,
  type JobCreateRequest,
  type JobStatusFilter,
} from "@/lib/jobs-api"

export const jobsQueryKey = ["jobs"] as const
export const apiKeysQueryKey = ["api-keys"] as const

export function useDashboardData({
  token,
  statusFilter,
  selectedJobId,
}: {
  token: string
  statusFilter: JobStatusFilter
  selectedJobId: string | null
}) {
  const queryClient = useQueryClient()

  const jobsQuery = useQuery({
    queryKey: [...jobsQueryKey, statusFilter],
    queryFn: () => listJobs({ token, status: statusFilter }),
    refetchInterval: 5_000,
  })

  const overviewJobsQuery = useQuery({
    queryKey: [...jobsQueryKey, "overview"],
    queryFn: () => listJobs({ token, status: "ALL" }),
    refetchInterval: 5_000,
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
    overviewJobsQuery,
    revokeApiKeyMutation,
  }
}
