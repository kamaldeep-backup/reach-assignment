import { AlertCircleIcon } from "lucide-react"
import type { FormEvent } from "react"
import { useState } from "react"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Spinner } from "@/components/ui/spinner"
import { Textarea } from "@/components/ui/textarea"
import {
  makeIdempotencyKey,
  samplePayload,
} from "@/features/dashboard/dashboard-utils"
import { getErrorMessage } from "@/lib/api-client"

type JobSubmitPayload = {
  idempotencyKey: string
  type: string
  priority: number
  payload: Record<string, unknown>
}

type JobSubmitCardProps = {
  isPending: boolean
  error: unknown
  onSubmit: (payload: JobSubmitPayload) => void
}

export function JobSubmitCard({
  isPending,
  error,
  onSubmit,
}: JobSubmitCardProps) {
  const [idempotencyKey, setIdempotencyKey] = useState(makeIdempotencyKey)
  const [jobType, setJobType] = useState("noop")
  const [priority, setPriority] = useState("0")
  const [payloadText, setPayloadText] = useState(samplePayload)
  const [formError, setFormError] = useState<string | null>(null)

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setFormError(null)

    let parsedPayload: unknown
    try {
      parsedPayload = JSON.parse(payloadText)
    } catch {
      setFormError("Payload must be valid JSON.")
      return
    }

    if (
      parsedPayload === null ||
      Array.isArray(parsedPayload) ||
      typeof parsedPayload !== "object"
    ) {
      setFormError("Payload must be a JSON object.")
      return
    }

    onSubmit({
      idempotencyKey: idempotencyKey.trim(),
      type: jobType.trim(),
      priority: Number(priority),
      payload: parsedPayload as Record<string, unknown>,
    })
    setIdempotencyKey(makeIdempotencyKey())
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Submit job</CardTitle>
        <CardDescription>
          Create a durable job with a client idempotency key.
        </CardDescription>
      </CardHeader>
      <form onSubmit={handleSubmit}>
        <CardContent>
          <FieldGroup>
            {formError ? (
              <Alert variant="destructive">
                <AlertCircleIcon />
                <AlertDescription>{formError}</AlertDescription>
              </Alert>
            ) : null}
            {error ? (
              <Alert variant="destructive">
                <AlertCircleIcon />
                <AlertDescription>{getErrorMessage(error)}</AlertDescription>
              </Alert>
            ) : null}

            <Field>
              <FieldLabel htmlFor="job-type">Type</FieldLabel>
              <Input
                id="job-type"
                value={jobType}
                onChange={(event) => setJobType(event.target.value)}
                required
                disabled={isPending}
              />
            </Field>

            <div className="grid gap-4 sm:grid-cols-[1fr_8rem]">
              <Field>
                <FieldLabel htmlFor="idempotency-key">
                  Idempotency key
                </FieldLabel>
                <Input
                  id="idempotency-key"
                  value={idempotencyKey}
                  onChange={(event) => setIdempotencyKey(event.target.value)}
                  required
                  disabled={isPending}
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="job-priority">Priority</FieldLabel>
                <Input
                  id="job-priority"
                  type="number"
                  min={0}
                  max={100}
                  value={priority}
                  onChange={(event) => setPriority(event.target.value)}
                  disabled={isPending}
                />
              </Field>
            </div>

            <Field>
              <FieldLabel htmlFor="job-payload">Payload</FieldLabel>
              <Textarea
                id="job-payload"
                className="min-h-40 font-mono text-sm"
                value={payloadText}
                onChange={(event) => setPayloadText(event.target.value)}
                disabled={isPending}
                required
              />
              <FieldDescription>
                Send a non-empty JSON object. The API stores it before workers
                claim the job.
              </FieldDescription>
            </Field>
          </FieldGroup>
        </CardContent>
        <CardFooter className="justify-end">
          <Button type="submit" disabled={isPending}>
            {isPending ? <Spinner data-icon="inline-start" /> : null}
            Submit job
          </Button>
        </CardFooter>
      </form>
    </Card>
  )
}
