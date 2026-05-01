import { LogOutIcon, ShieldCheckIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import type { CurrentUserResponse } from "@/lib/auth-api"

type DashboardHeaderProps = {
  currentUser?: CurrentUserResponse
  isLoading: boolean
  onLogout: () => void
}

export function DashboardHeader({
  currentUser,
  isLoading,
  onLogout,
}: DashboardHeaderProps) {
  return (
    <header className="flex flex-col gap-4 border-b bg-background px-4 py-4 md:flex-row md:items-center md:justify-between md:px-6">
      <div className="flex min-w-0 flex-col gap-1">
        <div className="flex items-center gap-2">
          <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-sm font-medium text-primary-foreground">
            R
          </div>
          <div className="min-w-0">
            <h1 className="truncate font-heading text-xl font-medium tracking-tight">
              {currentUser?.tenant.name ?? "Reach"}
            </h1>
            <p className="truncate text-sm text-muted-foreground">
              {isLoading ? "Loading workspace" : currentUser?.email}
            </p>
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <Badge variant="outline">
          <ShieldCheckIcon data-icon="inline-start" />
          {currentUser?.tenant.role ?? "owner"}
        </Badge>
        <Button variant="outline" onClick={onLogout}>
          <LogOutIcon data-icon="inline-start" />
          Logout
        </Button>
      </div>
    </header>
  )
}
