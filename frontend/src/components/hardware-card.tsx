import { createContext, useCallback, useContext, useEffect, useState } from "react"
import { Cpu, HardDrive, Info, Loader2, MemoryStick, MonitorCog, RefreshCw, Sparkles } from "lucide-react"
import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"
import { cn } from "@/lib/utils"

export interface Fit { level: "great" | "ok" | "slow" | "no" | "unknown"; label: string; need_gb?: number }

export interface HardwareInfo {
  os: { name: string; version: string }
  cpu: { name: string; cores: number; threads: number; max_ghz: number | null }
  ram: { total_gb: number; available_gb: number }
  gpus: { vendor: string; name: string; vram_gb: number | null; unified?: boolean; integrated?: boolean; backend?: string }[]
  disk: { free_gb: number; total_gb: number } | null
  notes: string[]
  recommendation: {
    llm: string
    voice: string
    context_size: number
    gpu: string | null
    gpu_mem_gb: number
    reasons: string[]
    model_fits: Record<string, Fit>
    voice_fits: Record<string, Fit>
  }
}

const HardwareContext = createContext<{ info: HardwareInfo | null; loading: boolean; rescan: () => Promise<void> }>(
  { info: null, loading: true, rescan: async () => {} })

/** One scan shared by every page (it's cheap to keep, slower to repeat). */
export function HardwareProvider({ children }: { children: React.ReactNode }) {
  const [info, setInfo] = useState<HardwareInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const load = useCallback(async (refresh = false) => {
    setLoading(true)
    try {
      setInfo(await api<HardwareInfo>(`/api/system/hardware${refresh ? "?refresh=true" : ""}`))
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }, [])
  useEffect(() => { load() }, [load])
  return <HardwareContext.Provider value={{ info, loading, rescan: () => load(true) }}>{children}</HardwareContext.Provider>
}

export const useHardware = () => useContext(HardwareContext)

const fitStyle: Record<Fit["level"], string> = {
  great: "border-success/40 text-success",
  ok: "border-warning/40 text-warning",
  slow: "border-warning/40 text-warning",
  no: "border-destructive/40 text-destructive",
  unknown: "border-border text-muted-foreground",
}
const fitIcon: Record<Fit["level"], string> = { great: "✓", ok: "◐", slow: "◔", no: "✕", unknown: "?" }

/** "Runs fully on your GPU" style badge; icon + text so colour is never the only signal. */
export function FitBadge({ fit, className }: { fit?: Fit; className?: string }) {
  if (!fit) return null
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium", fitStyle[fit.level], className)}
      title={fit.need_gb ? `Needs about ${fit.need_gb} GB of GPU memory to run fully on the GPU` : undefined}>
      <span aria-hidden>{fitIcon[fit.level]}</span> {fit.label}
    </span>
  )
}

function Spec({ icon: Icon, label, value }: { icon: React.ComponentType<{ className?: string }>; label: string; value: React.ReactNode }) {
  return (
    <div className="flex min-w-0 items-start gap-2.5">
      <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0">
        <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
        <div className="text-sm font-medium leading-snug">{value}</div>
      </div>
    </div>
  )
}

export function HardwareSummary({ compact, actions }: { compact?: boolean; actions?: React.ReactNode }) {
  const { info, loading, rescan } = useHardware()
  if (!info) {
    return (
      <div className="flex items-center gap-2 rounded-2xl border bg-card p-4 text-sm text-muted-foreground">
        {loading ? <><Loader2 className="size-4 animate-spin" /> Checking your computer…</> : "Couldn't scan this computer."}
      </div>
    )
  }
  const gpus = info.gpus.filter((g) => compact ? !g.integrated : true)
  const rec = info.recommendation
  return (
    <div className="rounded-2xl border bg-card p-5 shadow-xs">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Your computer</div>
        <Button variant="ghost" size="sm" className="h-7" onClick={rescan} disabled={loading}>
          {loading ? <Loader2 className="animate-spin" /> : <RefreshCw />} Rescan
        </Button>
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Spec icon={Cpu} label="Processor" value={<>{info.cpu.name}<div className="text-xs font-normal text-muted-foreground">{info.cpu.cores} cores · {info.cpu.threads} threads</div></>} />
        <Spec icon={MemoryStick} label="Memory (RAM)" value={<>{info.ram.total_gb} GB<div className="text-xs font-normal text-muted-foreground">{info.ram.available_gb} GB free now</div></>} />
        <Spec icon={MonitorCog} label={gpus.length > 1 ? "Graphics cards" : "Graphics card"} value={
          gpus.length ? gpus.map((g) => (
            <div key={g.name}>{g.name}<div className="text-xs font-normal text-muted-foreground">
              {g.vram_gb ? `${g.vram_gb} GB${g.unified ? " shared memory" : ""}` : "memory unknown"}{g.integrated ? " · integrated" : ""}</div></div>
          )) : <span className="text-muted-foreground">None detected</span>} />
        {info.disk && <Spec icon={HardDrive} label="Free disk" value={<>{info.disk.free_gb} GB<div className="text-xs font-normal text-muted-foreground">on the app's drive</div></>} />}
      </div>

      <div className="mt-4 rounded-xl bg-accent/50 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 text-sm font-medium"><Sparkles className="size-4 text-primary" /> Recommended for this PC</div>
          {actions}
        </div>
        <ul className="mt-2 space-y-1 text-[13px] text-muted-foreground">
          {rec.reasons.map((r) => <li key={r}>• {r}</li>)}
        </ul>
      </div>

      {info.notes.length > 0 && (
        <div className="mt-3 space-y-1 rounded-xl border border-warning/40 bg-warning/10 p-3 text-[13px]">
          <div className="flex items-center gap-1.5 font-medium"><Info className="size-4 text-warning" /> Some details couldn't be read</div>
          {info.notes.map((n) => <p key={n} className="text-muted-foreground">{n}</p>)}
          <p className="text-muted-foreground">The recommendation uses everything that was found. Nothing is wrong with the app.</p>
        </div>
      )}
    </div>
  )
}
