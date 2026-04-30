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
  }
}

type FastApiErrorDetail =
  | string
  | Array<{
      msg?: string
      loc?: Array<string | number>
    }>

type ApiErrorBody = {
  detail?: FastApiErrorDetail
}

const API_ORIGIN =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/+$/, "") ??
  "http://127.0.0.1:8000"
const API_PREFIX = `${API_ORIGIN}/api/v1`
const TOKEN_STORAGE_KEY = "reach.authToken.v1"

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
}

function formatErrorDetail(detail: FastApiErrorDetail | undefined) {
  if (typeof detail === "string") {
    return detail
  }

  if (Array.isArray(detail)) {
    return detail
      .map((item) => item.msg)
      .filter(Boolean)
      .join(" ")
  }

  return ""
}

async function readApiResponse<T>(response: Response): Promise<T> {
  const contentType = response.headers.get("content-type") ?? ""
  const body = contentType.includes("application/json")
    ? ((await response.json()) as ApiErrorBody | T)
    : null

  if (!response.ok) {
    const detail =
      body && typeof body === "object" && "detail" in body
        ? body.detail
        : undefined
    const message = formatErrorDetail(detail) || "Request failed"
    throw new ApiError(response.status, message)
  }

  return body as T
}

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

export function getErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message
  }

  return "Something went wrong"
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
    headers: {
      Authorization: `Bearer ${token}`,
    },
  })

  return readApiResponse<CurrentUserResponse>(response)
}
