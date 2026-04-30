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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  getErrorMessage,
  type LoginRequest,
  type RegisterRequest,
} from "@/lib/auth-api"

type AuthScreenProps = {
  onLogin: (payload: LoginRequest) => void
  onSignup: (payload: RegisterRequest) => void
  isLoginPending: boolean
  isSignupPending: boolean
  loginError: unknown
  signupError: unknown
}

function getFormValue(formData: FormData, name: string) {
  const value = formData.get(name)

  return typeof value === "string" ? value.trim() : ""
}

export function AuthScreen({
  onLogin,
  onSignup,
  isLoginPending,
  isSignupPending,
  loginError,
  signupError,
}: AuthScreenProps) {
  const handleLogin = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()

    const formData = new FormData(event.currentTarget)
    onLogin({
      email: getFormValue(formData, "email"),
      password: getFormValue(formData, "password"),
    })
  }

  const handleSignup = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()

    const formData = new FormData(event.currentTarget)
    onSignup({
      email: getFormValue(formData, "email"),
      password: getFormValue(formData, "password"),
      tenantName: getFormValue(formData, "tenantName"),
    })
  }

  return (
    <main className="flex min-h-svh items-center justify-center bg-background p-6">
      <div className="flex w-full max-w-sm flex-col gap-4">
        <div className="flex flex-col gap-1 text-center">
          <h1 className="font-heading text-2xl font-medium tracking-tight">
            Reach
          </h1>
          <p className="text-sm text-muted-foreground">
            Sign in or create a workspace.
          </p>
        </div>

        <Tabs defaultValue="login" className="w-full">
          <TabsList className="w-full">
            <TabsTrigger value="login">Login</TabsTrigger>
            <TabsTrigger value="signup">Signup</TabsTrigger>
          </TabsList>

          <TabsContent value="login">
            <Card>
              <CardHeader>
                <CardTitle>Welcome back</CardTitle>
                <CardDescription>
                  Enter your email and password to continue.
                </CardDescription>
              </CardHeader>
              <form onSubmit={handleLogin}>
                <CardContent>
                  <FieldGroup>
                    {loginError ? (
                      <Alert variant="destructive">
                        <AlertCircleIcon />
                        <AlertDescription>
                          {getErrorMessage(loginError)}
                        </AlertDescription>
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
                        disabled={isLoginPending}
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
                        disabled={isLoginPending}
                      />
                    </Field>
                  </FieldGroup>
                </CardContent>
                <CardFooter>
                  <Button
                    className="w-full"
                    type="submit"
                    disabled={isLoginPending}
                  >
                    {isLoginPending ? (
                      <Spinner data-icon="inline-start" />
                    ) : null}
                    Login
                  </Button>
                </CardFooter>
              </form>
            </Card>
          </TabsContent>

          <TabsContent value="signup">
            <Card>
              <CardHeader>
                <CardTitle>Create account</CardTitle>
                <CardDescription>
                  Start with one owner account and workspace.
                </CardDescription>
              </CardHeader>
              <form onSubmit={handleSignup}>
                <CardContent>
                  <FieldGroup>
                    {signupError ? (
                      <Alert variant="destructive">
                        <AlertCircleIcon />
                        <AlertDescription>
                          {getErrorMessage(signupError)}
                        </AlertDescription>
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
                        disabled={isSignupPending}
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
                        disabled={isSignupPending}
                      />
                    </Field>

                    <Field>
                      <FieldLabel htmlFor="signup-password">
                        Password
                      </FieldLabel>
                      <Input
                        id="signup-password"
                        name="password"
                        type="password"
                        autoComplete="new-password"
                        minLength={12}
                        required
                        disabled={isSignupPending}
                      />
                      <FieldDescription>
                        Use at least 12 characters.
                      </FieldDescription>
                    </Field>
                  </FieldGroup>
                </CardContent>
                <CardFooter>
                  <Button
                    className="w-full"
                    type="submit"
                    disabled={isSignupPending}
                  >
                    {isSignupPending ? (
                      <Spinner data-icon="inline-start" />
                    ) : null}
                    Create account
                  </Button>
                </CardFooter>
              </form>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </main>
  )
}
