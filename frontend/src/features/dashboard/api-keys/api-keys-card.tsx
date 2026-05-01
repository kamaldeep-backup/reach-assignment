import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { ApiKeyForm } from "@/features/dashboard/api-keys/api-key-form"
import { ApiKeyList } from "@/features/dashboard/api-keys/api-key-list"
import type { APIKeyCreateRequest, APIKeyResponse } from "@/lib/api-keys-api"

type ApiKeysCardProps = {
  keys: APIKeyResponse[]
  isLoading: boolean
  createError: unknown
  revokeError: unknown
  isCreating: boolean
  isRevoking: boolean
  onCreate: (payload: APIKeyCreateRequest) => void
  onRevoke: (apiKeyId: string) => void
}

export function ApiKeysCard({
  keys,
  isLoading,
  createError,
  revokeError,
  isCreating,
  isRevoking,
  onCreate,
  onRevoke,
}: ApiKeysCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>API keys</CardTitle>
        <CardDescription>
          Issue tenant-scoped keys for direct client access.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <ApiKeyForm
          createError={createError}
          isCreating={isCreating}
          onCreate={onCreate}
        />

        <Separator />

        <ApiKeyList
          keys={keys}
          isLoading={isLoading}
          isRevoking={isRevoking}
          revokeError={revokeError}
          onRevoke={onRevoke}
        />
      </CardContent>
    </Card>
  )
}
