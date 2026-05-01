import { AlertCircleIcon, BanIcon } from "lucide-react"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { formatDate } from "@/features/dashboard/dashboard-utils"
import { getErrorMessage } from "@/lib/api-client"
import type { APIKeyResponse } from "@/lib/api-keys-api"

type ApiKeyListProps = {
  keys: APIKeyResponse[]
  isLoading: boolean
  isRevoking: boolean
  revokeError: unknown
  onRevoke: (apiKeyId: string) => void
}

export function ApiKeyList({
  keys,
  isLoading,
  isRevoking,
  revokeError,
  onRevoke,
}: ApiKeyListProps) {
  return (
    <div className="flex flex-col gap-3">
      {revokeError ? (
        <Alert variant="destructive">
          <AlertCircleIcon />
          <AlertDescription>{getErrorMessage(revokeError)}</AlertDescription>
        </Alert>
      ) : null}

      {isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner />
          Loading API keys
        </div>
      ) : keys.length === 0 ? (
        <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
          No API keys have been issued for this tenant.
        </div>
      ) : (
        keys.map((apiKey) => (
          <div
            key={apiKey.apiKeyId}
            className="flex flex-col gap-3 rounded-lg border p-3"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate font-medium">{apiKey.name}</div>
                <div className="truncate text-xs text-muted-foreground">
                  {apiKey.keyPrefix}
                </div>
              </div>
              <Badge variant={apiKey.isActive ? "secondary" : "outline"}>
                {apiKey.isActive ? "Active" : "Revoked"}
              </Badge>
            </div>
            <div className="flex flex-wrap gap-1">
              {apiKey.scopes.map((scope) => (
                <Badge key={scope} variant="outline">
                  {scope}
                </Badge>
              ))}
            </div>
            <div className="grid gap-1 text-xs text-muted-foreground">
              <span>Created {formatDate(apiKey.createdAt)}</span>
              <span>Last used {formatDate(apiKey.lastUsedAt)}</span>
              <span>Expires {formatDate(apiKey.expiresAt)}</span>
            </div>
            <Button
              variant="destructive"
              size="sm"
              disabled={!apiKey.isActive || isRevoking}
              onClick={() => onRevoke(apiKey.apiKeyId)}
            >
              <BanIcon data-icon="inline-start" />
              Revoke
            </Button>
          </div>
        ))
      )}
    </div>
  )
}
