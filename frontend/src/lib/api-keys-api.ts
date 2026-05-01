import {
  API_PREFIX,
  getBearerHeaders,
  readApiResponse,
} from "@/lib/api-client"

export type APIKeyResponse = {
  apiKeyId: string
  name: string
  keyPrefix: string
  scopes: string[]
  isActive: boolean
  expiresAt: string | null
  lastUsedAt: string | null
  createdAt: string
  revokedAt: string | null
}

export type APIKeyCreateResponse = APIKeyResponse & {
  apiKey: string
}

export type APIKeyCreateRequest = {
  name: string
  scopes: string[]
  expiresAt?: string
}

export async function listApiKeys(token: string) {
  const response = await fetch(`${API_PREFIX}/api-keys`, {
    headers: getBearerHeaders(token),
  })

  return readApiResponse<APIKeyResponse[]>(response)
}

export async function createApiKey({
  token,
  payload,
}: {
  token: string
  payload: APIKeyCreateRequest
}) {
  const response = await fetch(`${API_PREFIX}/api-keys`, {
    method: "POST",
    headers: {
      ...getBearerHeaders(token),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  })

  return readApiResponse<APIKeyCreateResponse>(response)
}

export async function revokeApiKey({
  token,
  apiKeyId,
}: {
  token: string
  apiKeyId: string
}) {
  const response = await fetch(`${API_PREFIX}/api-keys/${apiKeyId}`, {
    method: "DELETE",
    headers: getBearerHeaders(token),
  })

  return readApiResponse<void>(response)
}
