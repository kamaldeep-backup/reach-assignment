export const samplePayload = JSON.stringify(
  {
    to: "customer@example.com",
    template: "welcome",
  },
  null,
  2
)

const dateFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
})

export function formatDate(value: string | null | undefined) {
  if (!value) {
    return "Never"
  }

  return dateFormatter.format(new Date(value))
}

export function makeIdempotencyKey() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `dashboard-${crypto.randomUUID()}`
  }

  return `dashboard-${Date.now()}-${Math.random().toString(16).slice(2)}`
}
