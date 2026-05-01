import { AlertCircleIcon } from "lucide-react"
import type { FormEvent } from "react"

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
import { getFormValue } from "@/features/auth/auth-utils"
import { getErrorMessage } from "@/lib/api-client"
import type { RegisterRequest } from "@/lib/auth-api"

type SignupFormProps = {
  error: unknown
  isPending: boolean
  onSignup: (payload: RegisterRequest) => void
}

export function SignupForm({ error, isPending, onSignup }: SignupFormProps) {
  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()

    const formData = new FormData(event.currentTarget)
    onSignup({
      email: getFormValue(formData, "email"),
      password: getFormValue(formData, "password"),
      tenantName: getFormValue(formData, "tenantName"),
    })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Create account</CardTitle>
        <CardDescription>
          Start with one owner account and workspace.
        </CardDescription>
      </CardHeader>
      <form onSubmit={handleSubmit}>
        <CardContent>
          <FieldGroup>
            {error ? (
              <Alert variant="destructive">
                <AlertCircleIcon />
                <AlertDescription>{getErrorMessage(error)}</AlertDescription>
              </Alert>
            ) : null}

            <Field>
              <FieldLabel htmlFor="signup-tenant">Workspace</FieldLabel>
              <Input
                id="signup-tenant"
                name="tenantName"
                autoComplete="organization"
                placeholder="Acme Corp"
                required
                disabled={isPending}
              />
            </Field>

            <Field>
              <FieldLabel htmlFor="signup-email">Email</FieldLabel>
              <Input
                id="signup-email"
                name="email"
                type="email"
                autoComplete="email"
                placeholder="you@example.com"
                required
                disabled={isPending}
              />
            </Field>

            <Field>
              <FieldLabel htmlFor="signup-password">Password</FieldLabel>
              <Input
                id="signup-password"
                name="password"
                type="password"
                autoComplete="new-password"
                minLength={12}
                required
                disabled={isPending}
              />
              <FieldDescription>Use at least 12 characters.</FieldDescription>
            </Field>
          </FieldGroup>
        </CardContent>
        <CardFooter>
          <Button className="w-full" type="submit" disabled={isPending}>
            {isPending ? <Spinner data-icon="inline-start" /> : null}
            Create account
          </Button>
        </CardFooter>
      </form>
    </Card>
  )
}
