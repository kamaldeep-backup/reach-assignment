import { AlertCircleIcon } from "lucide-react"
import type { FormEvent } from "react"
import { useState } from "react"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Spinner } from "@/components/ui/spinner"
import { getErrorMessage } from "@/lib/api-client"
import type { APIKeyCreateRequest } from "@/lib/api-keys-api"

type ApiKeyFormProps = {
  createError: unknown
  isCreating: boolean
  onCreate: (payload: APIKeyCreateRequest) => void
}

export function ApiKeyForm({
  createError,
  isCreating,
  onCreate,
}: ApiKeyFormProps) {
  const [name, setName] = useState("local client")
  const [readScope, setReadScope] = useState(true)
  const [writeScope, setWriteScope] = useState(true)
  const [expiresAt, setExpiresAt] = useState("")
  const [formError, setFormError] = useState<string | null>(null)

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setFormError(null)

    const scopes = [
      readScope ? "jobs:read" : null,
      writeScope ? "jobs:write" : null,
    ].filter((scope): scope is string => scope !== null)

    if (scopes.length === 0) {
      setFormError("Select at least one scope.")
      return
    }

    onCreate({
      name: name.trim(),
      scopes,
      expiresAt: expiresAt ? new Date(expiresAt).toISOString() : undefined,
    })
  }

  return (
    <form onSubmit={handleSubmit}>
      <FieldGroup>
        {formError ? (
          <Alert variant="destructive">
            <AlertCircleIcon />
            <AlertDescription>{formError}</AlertDescription>
          </Alert>
        ) : null}
        {createError ? (
          <Alert variant="destructive">
            <AlertCircleIcon />
            <AlertDescription>{getErrorMessage(createError)}</AlertDescription>
          </Alert>
        ) : null}

        <Field>
          <FieldLabel htmlFor="api-key-name">Name</FieldLabel>
          <Input
            id="api-key-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            disabled={isCreating}
            required
          />
        </Field>

        <FieldSet>
          <FieldLegend variant="label">Scopes</FieldLegend>
          <div className="grid gap-2 sm:grid-cols-2">
            <Field orientation="horizontal">
              <input
                id="scope-read"
                type="checkbox"
                className="mt-0.5 size-4 accent-primary"
                checked={readScope}
                onChange={(event) => setReadScope(event.target.checked)}
                disabled={isCreating}
              />
              <FieldContent>
                <FieldLabel htmlFor="scope-read">jobs:read</FieldLabel>
                <FieldDescription>List and inspect jobs.</FieldDescription>
              </FieldContent>
            </Field>
            <Field orientation="horizontal">
              <input
                id="scope-write"
                type="checkbox"
                className="mt-0.5 size-4 accent-primary"
                checked={writeScope}
                onChange={(event) => setWriteScope(event.target.checked)}
                disabled={isCreating}
              />
              <FieldContent>
                <FieldLabel htmlFor="scope-write">jobs:write</FieldLabel>
                <FieldDescription>Submit new jobs.</FieldDescription>
              </FieldContent>
            </Field>
          </div>
        </FieldSet>

        <Field>
          <FieldLabel htmlFor="api-key-expiry">Expires at</FieldLabel>
          <Input
            id="api-key-expiry"
            type="datetime-local"
            value={expiresAt}
            onChange={(event) => setExpiresAt(event.target.value)}
            disabled={isCreating}
          />
          <FieldDescription>Leave blank for a non-expiring key.</FieldDescription>
        </Field>

        <Button type="submit" disabled={isCreating}>
          {isCreating ? <Spinner data-icon="inline-start" /> : null}
          Create API key
        </Button>
      </FieldGroup>
    </form>
  )
}
