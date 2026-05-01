type FastApiErrorDetail =
  | string
  | Array<{
      msg?: string
      loc?: Array<string | number>
    }>

type ApiErrorBody = {
  detail?: FastApiErrorDetail
}

export const API_ORIGIN =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/+$/, "") ??
  "http://127.0.0.1:8000"
export const API_PREFIX = `${API_ORIGIN}/api/v1`

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

export async function readApiResponse<T>(response: Response): Promise<T> {
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

export function getBearerHeaders(token: string): HeadersInit {
  return {
    Authorization: `Bearer ${token}`,
  }
}

export function getErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message
  }

  return "Something went wrong"
}
