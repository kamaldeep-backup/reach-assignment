import type { LucideIcon } from "lucide-react"
import { ActivityIcon, KeyRoundIcon, ServerIcon } from "lucide-react"

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import type { CurrentUserResponse } from "@/lib/auth-api"

type WorkspaceLimitsCardProps = {
  activeKeys: number
  currentUser?: CurrentUserResponse
}

export function WorkspaceLimitsCard({
  activeKeys,
  currentUser,
}: WorkspaceLimitsCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Workspace limits</CardTitle>
        <CardDescription>
          Tenant guardrails returned by the authenticated session.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-3">
        <LimitItem
          icon={ActivityIcon}
          label="Submit rate"
          value={`${currentUser?.tenant.submitRateLimit ?? 0}/min`}
        />
        <LimitItem
          icon={ServerIcon}
          label="Max running jobs"
          value={String(currentUser?.tenant.maxRunningJobs ?? 0)}
        />
        <LimitItem
          icon={KeyRoundIcon}
          label="Active API keys"
          value={String(activeKeys)}
        />
      </CardContent>
    </Card>
  )
}

function LimitItem({
  icon: Icon,
  label,
  value,
}: {
  icon: LucideIcon
  label: string
  value: string
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg border p-3">
      <div className="flex size-8 items-center justify-center rounded-lg bg-muted">
        <Icon className="size-4 text-muted-foreground" aria-hidden="true" />
      </div>
      <div className="min-w-0">
        <div className="truncate text-sm font-medium">{value}</div>
        <div className="truncate text-xs text-muted-foreground">{label}</div>
      </div>
    </div>
  )
}
