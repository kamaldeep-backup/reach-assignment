import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { LoginForm } from "@/features/auth/components/login-form"
import { SignupForm } from "@/features/auth/components/signup-form"
import type { LoginRequest, RegisterRequest } from "@/lib/auth-api"

type AuthScreenProps = {
  onLogin: (payload: LoginRequest) => void
  onSignup: (payload: RegisterRequest) => void
  isLoginPending: boolean
  isSignupPending: boolean
  loginError: unknown
  signupError: unknown
}

export function AuthScreen({
  onLogin,
  onSignup,
  isLoginPending,
  isSignupPending,
  loginError,
  signupError,
}: AuthScreenProps) {
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
            <LoginForm
              error={loginError}
              isPending={isLoginPending}
              onLogin={onLogin}
            />
          </TabsContent>

          <TabsContent value="signup">
            <SignupForm
              error={signupError}
              isPending={isSignupPending}
              onSignup={onSignup}
            />
          </TabsContent>
        </Tabs>
      </div>
    </main>
  )
}
