import { useEffect, useMemo, useRef, useState } from "react"
import { Activity, ChevronDown, ChevronUp, Info, Power, Thermometer } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { useSettings } from "@/context/SettingsContext"
import { useSystemStatus } from "@/context/SystemStatusContext"
import { api } from "@/lib/api"

type Comp = "llm" | "voice" | "window" | "app"

interface Usage {
  time: number
  cpu: { total_pct: number; by: Record<Comp, number>; threads: number }
  ram: { total_gb: number; used_gb: number; by: Record<Comp, number> }
  gpus: {
    name: string
    vram_total_gb: number | null
    vram_used_gb: number
    util_pct: number | null
    temp_c: number | null
    by_vram: Record<Comp, number>
    by_util: Partial<Record<Comp, number>>
    per_app: boolean
  }[]
  notes: string[]
}

// Fixed order = fixed colour slot (validated palette); "other" is the neutral rest of the PC.
const PARTS: { key: Comp | "other"; label: string; color: string }[] = [
  { key: "llm", label: "Brain (LLM)", color: "var(--viz-llm)" },
  { key: "voice", label: "Voice", color: "var(--viz-voice)" },
  { key: "window", label: "Character window", color: "var(--viz-window)" },
  { key: "app", label: "App & speech/vision", color: "var(--viz-app)" },
  { key: "other", label: "Other programs", color: "var(--viz-other)" },
]
const HISTORY = 60 // samples (~2 minutes at 2 s)
const OPEN_KEY = "lav.perf.open"

interface Segment { key: string; label: string; color: string; value: number }

function split(by: Partial<Record<Comp, number>> | undefined, total: number): Segment[] {
  const ours = PARTS.slice(0, 4).map((p) => ({ ...p, value: Math.max(0, by?.[p.key as Comp] ?? 0) }))
  const sum = ours.reduce((a, b) => a + b.value, 0)
  return [...ours, { ...PARTS[4], value: Math.max(0, total - sum) }]
}

function fmt(v: number, unit: string) {
  if (unit === "%") return `${Math.round(v)}%`
  return `${v >= 10 ? v.toFixed(0) : v.toFixed(1)} ${unit}`
}

/** One stacked bar: segments with 2px surface gaps on an empty track; hover shows exact values. */
function StackBar({ segments, max, unit, height = 8, label }: { segments: Segment[]; max: number; unit: string; height?: number; label: string }) {
  const [hover, setHover] = useState<Segment | null>(null)
  const visible = segments.filter((s) => max > 0 && s.value / max > 0.004)
  const used = segments.reduce((a, b) => a + b.value, 0)
  return (
    <div className="relative w-full" role="img"
      aria-label={`${label}: ${segments.map((s) => `${s.label} ${fmt(s.value, unit)}`).join(", ")} of ${fmt(max, unit)}`}>
      <div className="flex w-full gap-[2px] overflow-hidden rounded-[4px] bg-muted" style={{ height }}>
        {visible.map((s) => (
          <div key={s.key} className="h-full transition-[width] duration-500 first:rounded-l-[4px] last:rounded-r-[4px]"
            style={{ width: `${Math.min(100, (s.value / max) * 100)}%`, background: s.color }}
            onMouseEnter={() => setHover(s)} onMouseLeave={() => setHover(null)} />
        ))}
      </div>
      {hover && (
        <div className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-2 -translate-x-1/2 whitespace-nowrap rounded-md border bg-popover px-2 py-1 text-xs shadow-md">
          <span className="mr-1.5 inline-block size-2 rounded-full align-middle" style={{ background: hover.color }} />
          {hover.label}: <span className="font-medium tabular">{fmt(hover.value, unit)}</span>
          <span className="text-muted-foreground"> · total {fmt(used, unit)} of {fmt(max, unit)}</span>
        </div>
      )}
    </div>
  )
}

/** Tiny single-series line (total over time). */
function Sparkline({ values, max, unit, label }: { values: number[]; max: number; unit: string; label: string }) {
  const w = 220, h = 44
  const pts = values.map((v, i) => `${(i / (HISTORY - 1)) * w},${h - 2 - (Math.min(v, max) / (max || 1)) * (h - 4)}`).join(" ")
  const last = values[values.length - 1] ?? 0
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-medium tabular">{fmt(last, unit)}{unit !== "%" && max ? <span className="text-muted-foreground"> / {fmt(max, unit)}</span> : null}</span>
      </div>
      <svg width="100%" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="h-11 w-full overflow-visible" aria-hidden>
        <line x1="0" x2={w} y1={h - 2} y2={h - 2} stroke="var(--border)" strokeWidth="1" />
        {values.length > 1 && <polyline points={pts} fill="none" stroke="var(--primary)" strokeWidth="2" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />}
      </svg>
    </div>
  )
}

export function PerformanceDock() {
  const { settings } = useSettings()
  const { status, refresh } = useSystemStatus()
  const enabled = settings["ui.performanceBar"] !== false
  const [usage, setUsage] = useState<Usage | null>(null)
  const [vramFallback, setVramFallback] = useState<number | null>(null)
  const [open, setOpen] = useState(() => {
    try { return localStorage.getItem(OPEN_KEY) === "1" } catch { return false }
  })
  const history = useRef<{ cpu: number[]; ram: number[]; vram: number[]; gpu: number[] }>({ cpu: [], ram: [], vram: [], gpu: [] })
  const [, tick] = useState(0)

  useEffect(() => {
    if (!enabled) return
    api<{ gpus: { vram_gb?: number }[] }>("/api/system/hardware")
      .then((h) => setVramFallback(Math.max(0, ...h.gpus.map((g) => g.vram_gb ?? 0)) || null)).catch(() => undefined)
    let stop = false
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      if (!document.hidden) {
        try {
          const u = await api<Usage>("/api/system/usage")
          if (stop) return
          setUsage(u)
          const g = u.gpus[0]
          const push = (arr: number[], v: number) => { arr.push(v); if (arr.length > HISTORY) arr.shift() }
          push(history.current.cpu, u.cpu.total_pct)
          push(history.current.ram, u.ram.used_gb)
          push(history.current.vram, g?.vram_used_gb ?? 0)
          push(history.current.gpu, g?.util_pct ?? 0)
          tick((t) => t + 1)
        } catch { /* backend offline: the shell shows the disconnected screen */ }
      }
      if (!stop) timer = setTimeout(poll, 2000)
    }
    poll()
    return () => { stop = true; clearTimeout(timer) }
  }, [enabled])

  const toggle = () => setOpen((o) => {
    try { localStorage.setItem(OPEN_KEY, o ? "0" : "1") } catch { /* ignore */ }
    return !o
  })

  const gpu = usage?.gpus[0]
  const vramTotal = gpu?.vram_total_gb ?? vramFallback ?? 0
  const meters = useMemo(() => {
    if (!usage) return []
    const m = [
      { id: "cpu", label: "CPU", unit: "%", max: 100, segments: split(usage.cpu.by, usage.cpu.total_pct), used: usage.cpu.total_pct },
      { id: "ram", label: "RAM", unit: "GB", max: usage.ram.total_gb, segments: split(usage.ram.by, usage.ram.used_gb), used: usage.ram.used_gb },
    ]
    if (gpu) {
      m.push({ id: "vram", label: "GPU memory", unit: "GB", max: vramTotal || gpu.vram_used_gb,
        segments: gpu.per_app ? split(gpu.by_vram, gpu.vram_used_gb) : [{ ...PARTS[4], label: "All programs (per-app not available)", value: gpu.vram_used_gb }],
        used: gpu.vram_used_gb })
      if (gpu.util_pct != null) {
        const hasUtil = Object.keys(gpu.by_util || {}).length > 0
        m.push({ id: "gpu", label: "GPU load", unit: "%", max: 100,
          segments: hasUtil ? split(gpu.by_util, gpu.util_pct) : [{ ...PARTS[4], label: "All programs", value: gpu.util_pct }],
          used: gpu.util_pct })
      }
    }
    return m
  }, [usage, gpu, vramTotal])

  if (!enabled) return null

  const rows = PARTS.map((p) => {
    const get = (m: { segments: Segment[] } | undefined) => m?.segments.find((s) => s.key === p.key)?.value
    return { ...p, cpu: get(meters[0]), ram: get(meters[1]), vram: get(meters.find((m) => m.id === "vram")), gpu: get(meters.find((m) => m.id === "gpu")) }
  })
  const llmLoaded = status?.llm.provider === "local" && ["ready", "loading"].includes(status?.llm.state ?? "")

  return (
    <div className="shrink-0 border-t bg-sidebar/80 backdrop-blur">
      <button onClick={toggle} aria-expanded={open}
        className="flex w-full items-center gap-4 px-4 py-2 text-left hover:bg-accent/40 focus-visible:outline-2">
        <span className="flex shrink-0 items-center gap-1.5 text-xs font-medium"><Activity className="size-3.5 text-primary" /> Performance</span>
        <div className="grid min-w-0 flex-1 grid-cols-2 gap-x-5 gap-y-1 lg:grid-cols-4">
          {meters.length === 0 && <span className="text-xs text-muted-foreground">Measuring…</span>}
          {meters.map((m) => (
            <div key={m.id} className="flex min-w-0 items-center gap-2">
              <span className="w-[4.5rem] shrink-0 text-[11px] text-muted-foreground">{m.label}</span>
              <div className="min-w-0 flex-1"><StackBar segments={m.segments} max={m.max} unit={m.unit} label={m.label} /></div>
              <span className="w-[4.75rem] shrink-0 text-right text-[11px] tabular">
                {m.unit === "%" ? fmt(m.used, "%") : `${m.used.toFixed(1)}/${m.max.toFixed(0)} GB`}
              </span>
            </div>
          ))}
        </div>
        <span className="hidden shrink-0 items-center gap-2.5 text-[11px] text-muted-foreground 2xl:flex" aria-hidden>
          {PARTS.map((p) => (
            <span key={p.key} className="inline-flex items-center gap-1"><span className="size-2 rounded-sm" style={{ background: p.color }} />{p.label.split(" (")[0]}</span>
          ))}
        </span>
        {open ? <ChevronDown className="size-4 shrink-0" /> : <ChevronUp className="size-4 shrink-0" />}
      </button>

      {open && usage && (
        <div className="grid max-h-[40vh] grid-cols-1 gap-6 overflow-y-auto border-t px-4 py-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <div className="min-w-0">
            <table className="w-full text-xs tabular">
              <caption className="mb-2 text-left text-xs font-medium text-muted-foreground">What is using your computer right now</caption>
              <thead>
                <tr className="text-muted-foreground">
                  <th className="py-1 text-left font-normal">Part</th>
                  <th className="py-1 text-right font-normal">CPU</th>
                  <th className="py-1 text-right font-normal">RAM</th>
                  {meters.some((m) => m.id === "vram") && <th className="py-1 text-right font-normal">GPU memory</th>}
                  {meters.some((m) => m.id === "gpu") && <th className="py-1 text-right font-normal">GPU load</th>}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.key} className="border-t border-border/60">
                    <td className="py-1.5"><span className="mr-2 inline-block size-2.5 rounded-sm align-middle" style={{ background: r.color }} />{r.label}</td>
                    <td className="py-1.5 text-right">{r.cpu != null ? fmt(r.cpu, "%") : "–"}</td>
                    <td className="py-1.5 text-right">{r.ram != null ? fmt(r.ram, "GB") : "–"}</td>
                    {meters.some((m) => m.id === "vram") && <td className="py-1.5 text-right">{gpu?.per_app ? fmt(r.vram ?? 0, "GB") : r.key === "other" ? fmt(gpu?.vram_used_gb ?? 0, "GB") + " (all)" : "n/a"}</td>}
                    {meters.some((m) => m.id === "gpu") && <td className="py-1.5 text-right">{r.gpu != null ? fmt(r.gpu, "%") : "n/a"}</td>}
                  </tr>
                ))}
                <tr className="border-t font-medium">
                  <td className="py-1.5">Total in use</td>
                  <td className="py-1.5 text-right">{fmt(usage.cpu.total_pct, "%")} <span className="font-normal text-muted-foreground">of {usage.cpu.threads} threads</span></td>
                  <td className="py-1.5 text-right">{fmt(usage.ram.used_gb, "GB")} <span className="font-normal text-muted-foreground">/ {fmt(usage.ram.total_gb, "GB")}</span></td>
                  {meters.some((m) => m.id === "vram") && <td className="py-1.5 text-right">{fmt(gpu!.vram_used_gb, "GB")} <span className="font-normal text-muted-foreground">/ {fmt(vramTotal, "GB")}</span></td>}
                  {meters.some((m) => m.id === "gpu") && <td className="py-1.5 text-right">{fmt(gpu!.util_pct ?? 0, "%")}</td>}
                </tr>
              </tbody>
            </table>
            {usage.notes.length > 0 && (
              <ul className="mt-3 space-y-1">
                {usage.notes.map((n) => (
                  <li key={n} className="flex gap-1.5 text-[11px] text-muted-foreground"><Info className="mt-0.5 size-3 shrink-0" /> {n}</li>
                ))}
              </ul>
            )}
          </div>
          <div className="min-w-0 space-y-3">
            <div className="grid grid-cols-2 gap-x-5 gap-y-3">
              <Sparkline label="CPU (2 min)" values={history.current.cpu} max={100} unit="%" />
              <Sparkline label="RAM (2 min)" values={history.current.ram} max={usage.ram.total_gb} unit="GB" />
              {gpu && <Sparkline label="GPU memory (2 min)" values={history.current.vram} max={vramTotal} unit="GB" />}
              {gpu?.util_pct != null && <Sparkline label="GPU load (2 min)" values={history.current.gpu} max={100} unit="%" />}
            </div>
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              {gpu && <span className="mr-auto truncate">{gpu.name}{gpu.temp_c != null && <span className="ml-2 inline-flex items-center gap-0.5"><Thermometer className="size-3" />{gpu.temp_c}°C</span>}</span>}
              {llmLoaded && (
                <Button size="sm" variant="outline" onClick={() => api("/api/llm/unload", { method: "POST" })
                  .then(() => { toast.success("Model unloaded; its memory is free for other programs."); refresh() })
                  .catch((e) => toast.error(e.message))}>
                  <Power /> Unload model to free memory
                </Button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
