import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react"

export type LLMState = "stopped" | "loading" | "ready" | "error"
export type EngineState = "not_installed" | "installing" | "stopped" | "starting" | "ready" | "error"

export interface SystemStatus {
  version: string
  llm: {
    provider: "local" | "remote"
    remote?: { preset: string; base_url: string; model: string; has_key: boolean }
    state: LLMState
    error: string | null
    runtime_installed: boolean
    model_id: string | null
    model_name: string | null
    model_downloaded: boolean
    loaded_model_id: string | null
    vision_active: boolean
    options: Record<string, unknown>
  }
  /** source "local" = engines on this PC; otherwise a remote voice service (voicebox, openai, elevenlabs) */
  tts: { source: string; active_engine: string; current_voice: string | null; state: EngineState; error: string | null }
  gpu: { kind: string; name?: string }
  platform: string
}

interface Ctx {
  status: SystemStatus | null
  /** False when the backend stopped answering (e.g. after Quit). */
  connected: boolean
  refresh: () => Promise<void>
}

const SystemStatusContext = createContext<Ctx>({ status: null, connected: true, refresh: async () => {} })

export function SystemStatusProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [connected, setConnected] = useState(true)
  const failures = useRef(0)

  const refresh = useCallback(async () => {
    try {
      const res = await fetch("/api/system/status")
      if (!res.ok) throw new Error(String(res.status))
      setStatus(await res.json())
      failures.current = 0
      setConnected(true)
    } catch {
      failures.current += 1
      if (failures.current >= 2) setConnected(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    let timer: ReturnType<typeof setTimeout>
    const loop = () => {
      // Poll faster while something is changing, slower when idle or hidden.
      const busy = status?.llm.state === "loading" || ["starting", "installing"].includes(status?.tts.state ?? "")
      const delay = document.hidden ? 10000 : busy ? 1500 : 4000
      timer = setTimeout(async () => { await refresh(); loop() }, delay)
    }
    loop()
    return () => clearTimeout(timer)
  }, [refresh, status?.llm.state, status?.tts.state])

  return <SystemStatusContext.Provider value={{ status, connected, refresh }}>{children}</SystemStatusContext.Provider>
}

export const useSystemStatus = () => useContext(SystemStatusContext)
