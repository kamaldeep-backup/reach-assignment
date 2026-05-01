import { useEffect, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"

import { jobsQueryKey } from "@/features/dashboard/dashboard-queries"
import { getJobsStreamUrl, type JobStreamMessage } from "@/lib/jobs-api"

export type JobStatusStreamState =
  | "connecting"
  | "connected"
  | "reconnecting"
  | "disconnected"

export function useJobStatusStream({ token }: { token: string }) {
  const queryClient = useQueryClient()
  const [state, setState] = useState<JobStatusStreamState>("connecting")

  useEffect(() => {
    let socket: WebSocket | null = null
    let reconnectTimer: number | undefined
    let shouldReconnect = true

    const connect = () => {
      socket = new WebSocket(getJobsStreamUrl(token))
      setState((current) =>
        current === "disconnected" ? "reconnecting" : "connecting"
      )

      socket.onopen = () => {
        setState("connected")
        void queryClient.invalidateQueries({ queryKey: jobsQueryKey })
      }

      socket.onmessage = (event) => {
        const message = parseStreamMessage(event.data)
        if (message?.type === "job.event") {
          void queryClient.invalidateQueries({ queryKey: jobsQueryKey })
        }
      }

      socket.onclose = () => {
        if (!shouldReconnect) {
          setState("disconnected")
          return
        }

        setState("reconnecting")
        reconnectTimer = window.setTimeout(connect, 2_000)
      }

      socket.onerror = () => {
        socket?.close()
      }
    }

    connect()

    return () => {
      shouldReconnect = false
      window.clearTimeout(reconnectTimer)
      socket?.close()
    }
  }, [queryClient, token])

  return state
}

function parseStreamMessage(data: string): JobStreamMessage | null {
  try {
    return JSON.parse(data) as JobStreamMessage
  } catch {
    return null
  }
}
