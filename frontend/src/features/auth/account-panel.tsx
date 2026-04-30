import { LogOutIcon } from "lucide-react"

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
import { Spinner } from "@/components/ui/spinner"
import { getErrorMessage, type CurrentUserResponse } from "@/lib/auth-api"

type AccountPanelProps = {
  currentUser?: CurrentUserResponse
  error: unknown
  isLoading: boolean
  onLogout: () => void
}

export function AccountPanel({
  currentUser,
  error,
  isLoading,
  onLogout,
}: AccountPanelProps) {
  return (
    <main className="flex min-h-svh items-center justify-center bg-background p-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Account</CardTitle>
          <CardDescription>
            Your session is connected to the backend.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Spinner />
              Loading account
            </div>
          ) : error ? (
            <Alert variant="destructive">
              <AlertDescription>{getErrorMessage(error)}</AlertDescription>
            </Alert>
          ) : (
            <dl className="flex flex-col gap-3 text-sm">
              <div className="flex items-center justify-between gap-4">
                <dt className="text-muted-foreground">Email</dt>
                <dd className="truncate font-medium">{currentUser?.email}</dd>
              </div>
              <div className="flex items-center justify-between gap-4">
                <dt className="text-muted-foreground">Workspace</dt>
                <dd className="truncate font-medium">
                  {currentUser?.tenant.name}
                </dd>
              </div>
              <div className="flex items-center justify-between gap-4">
                <dt className="text-muted-foreground">Role</dt>
                <dd className="truncate font-medium">
                  {currentUser?.tenant.role}
                </dd>
              </div>
            </dl>
          )}
        </CardContent>
        <CardFooter>
          <Button className="w-full" variant="outline" onClick={onLogout}>
            <LogOutIcon data-icon="inline-start" />
            Logout
          </Button>
        </CardFooter>
      </Card>
    </main>
  )
}
