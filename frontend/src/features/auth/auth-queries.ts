import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

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

export const currentUserQueryKey = ["auth", "current-user"] as const

export function useAuth() {
  const queryClient = useQueryClient()
  const [token, setToken] = useState(() => getStoredToken())

  const currentUserQuery = useQuery({
    queryKey: currentUserQueryKey,
    queryFn: () => getCurrentUser(token ?? ""),
    enabled: token !== null,
  })

  const applyToken = (response: TokenResponse) => {
    storeToken(response.access_token)
    setToken(response.access_token)
  }

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

  const logout = () => {
    clearStoredToken()
    setToken(null)
    queryClient.setQueryData<CurrentUserResponse | undefined>(
      currentUserQueryKey,
      undefined
    )
    queryClient.removeQueries({ queryKey: currentUserQueryKey })
  }

  return {
    currentUserQuery,
    isAuthenticated: token !== null,
    loginMutation,
    logout,
    signupMutation,
  }
}
