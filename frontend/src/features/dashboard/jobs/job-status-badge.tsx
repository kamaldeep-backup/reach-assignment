import { Badge } from "@/components/ui/badge"
import type { JobStatus } from "@/lib/jobs-api"

export function JobStatusBadge({ status }: { status: JobStatus }) {
  const variant =
    status === "SUCCEEDED"
      ? "default"
      : status === "FAILED" || status === "DEAD_LETTERED"
        ? "destructive"
        : status === "RUNNING"
          ? "secondary"
          : "outline"

  return <Badge variant={variant}>{status.replace("_", " ")}</Badge>
}
