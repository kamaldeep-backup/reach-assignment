import type { LucideIcon } from "lucide-react"

import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

export type Metric = {
  label: string
  value: string
  detail: string
  icon: LucideIcon
}

export function DashboardMetrics({ metrics }: { metrics: Metric[] }) {
  return (
    <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {metrics.map((metric) => (
        <MetricCard key={metric.label} metric={metric} />
      ))}
    </section>
  )
}

function MetricCard({ metric }: { metric: Metric }) {
  const Icon = metric.icon

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>{metric.label}</CardTitle>
        <CardAction>
          <Icon className="size-4 text-muted-foreground" aria-hidden="true" />
        </CardAction>
        <CardDescription>{metric.detail}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-medium tracking-tight">
          {metric.value}
        </div>
      </CardContent>
    </Card>
  )
}
