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
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Spinner } from "@/components/ui/spinner"
import { getFormValue } from "@/features/auth/auth-utils"
import { getErrorMessage } from "@/lib/api-client"
import type { LoginRequest } from "@/lib/auth-api"

type LoginFormProps = {
  error: unknown
  isPending: boolean
  onLogin: (payload: LoginRequest) => void
}

export function LoginForm({ error, isPending, onLogin }: LoginFormProps) {
  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()

    const formData = new FormData(event.currentTarget)
    onLogin({
      email: getFormValue(formData, "email"),
      password: getFormValue(formData, "password"),
    })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Welcome back</CardTitle>
        <CardDescription>
          Enter your email and password to continue.
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
              <FieldLabel htmlFor="login-email">Email</FieldLabel>
              <Input
                id="login-email"
                name="email"
                type="email"
                autoComplete="email"
                placeholder="you@example.com"
                required
                disabled={isPending}
              />
            </Field>

            <Field>
              <FieldLabel htmlFor="login-password">Password</FieldLabel>
              <Input
                id="login-password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                disabled={isPending}
              />
            </Field>
          </FieldGroup>
        </CardContent>
        <CardFooter>
          <Button className="w-full" type="submit" disabled={isPending}>
            {isPending ? <Spinner data-icon="inline-start" /> : null}
            Login
          </Button>
        </CardFooter>
      </form>
    </Card>
  )
}
