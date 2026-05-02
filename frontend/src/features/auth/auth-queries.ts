import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback, useState } from "react"

import {
  clearStoredToken,
  getCurrentUser,
  getStoredToken,
  login,
  registerAccount,
  storeToken,
  type CurrentUserResponse,
  type LoginRequest,
  type RegisterRequest,
  type TokenResponse,
} from "@/lib/auth-api"
import { ApiError } from "@/lib/api-client"

export const currentUserQueryKey = ["auth", "current-user"] as const

export function useAuth() {
  const queryClient = useQueryClient()
  const [token, setToken] = useState(() => getStoredToken())

  const clearAuth = useCallback(() => {
    clearStoredToken()
    setToken(null)
    queryClient.setQueryData<CurrentUserResponse | undefined>(
      currentUserQueryKey,
      undefined
    )
    queryClient.removeQueries({ queryKey: currentUserQueryKey })
  }, [queryClient])

  const currentUserQuery = useQuery({
    queryKey: currentUserQueryKey,
    queryFn: async () => {
      try {
        return await getCurrentUser(token ?? "")
      } catch (error) {
        if (isAuthError(error)) {
          clearAuth()
        }
        throw error
      }
    },
    enabled: token !== null,
    retry: (failureCount, error) => !isAuthError(error) && failureCount < 3,
  })

  const applyToken = useCallback((response: TokenResponse) => {
    storeToken(response.access_token)
    setToken(response.access_token)
  }, [])

  const loginMutation = useMutation({
    mutationFn: (payload: LoginRequest) => login(payload),
    onSuccess: (response) => {
      applyToken(response)
      void queryClient.invalidateQueries({ queryKey: currentUserQueryKey })
    },
  })

  const signupMutation = useMutation({
    mutationFn: async (payload: RegisterRequest) => {
      await registerAccount(payload)
      return login({ email: payload.email, password: payload.password })
    },
    onSuccess: (response) => {
      applyToken(response)
      void queryClient.invalidateQueries({ queryKey: currentUserQueryKey })
    },
  })

  return {
    currentUserQuery,
    isAuthenticated: token !== null,
    loginMutation,
    logout: clearAuth,
    signupMutation,
    token,
  }
}

function isAuthError(error: unknown) {
  return error instanceof ApiError && (error.status === 401 || error.status === 403)
}
