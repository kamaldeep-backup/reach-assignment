import { API_PREFIX, getBearerHeaders, readApiResponse } from "@/lib/api-client"

export type LoginRequest = {
  email: string
  password: string
}

export type RegisterRequest = LoginRequest & {
  tenantName: string
}

export type RegisterResponse = {
  userId: string
  tenantId: string
  email: string
}

export type TokenResponse = {
  access_token: string
  token_type: "bearer"
}

export type CurrentUserResponse = {
  userId: string
  tenantId: string
  email: string
  isActive: boolean
  createdAt: string
  tenant: {
    id: string
    name: string
    role: string
    maxRunningJobs: number
    submitRateLimit: number
  }
}

const TOKEN_STORAGE_KEY = "reach.authToken.v1"

export function getStoredToken() {
  if (typeof window === "undefined") {
    return null
  }

  return localStorage.getItem(TOKEN_STORAGE_KEY)
}

export function storeToken(token: string) {
  if (typeof window === "undefined") {
    return
  }

  localStorage.setItem(TOKEN_STORAGE_KEY, token)
}

export function clearStoredToken() {
  if (typeof window === "undefined") {
    return
  }

  localStorage.removeItem(TOKEN_STORAGE_KEY)
}

export async function registerAccount(payload: RegisterRequest) {
  const response = await fetch(`${API_PREFIX}/auth/register`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  })

  return readApiResponse<RegisterResponse>(response)
}

export async function login(payload: LoginRequest) {
  const form = new URLSearchParams()
  form.set("username", payload.email)
  form.set("password", payload.password)

  const response = await fetch(`${API_PREFIX}/auth/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: form,
  })

  return readApiResponse<TokenResponse>(response)
}

export async function getCurrentUser(token: string) {
  const response = await fetch(`${API_PREFIX}/auth/me`, {
    headers: getBearerHeaders(token),
  })

  return readApiResponse<CurrentUserResponse>(response)
}
