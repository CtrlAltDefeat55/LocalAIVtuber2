import React from "react"
import { cn } from "@/lib/utils"

/** Consistent page header: title, one-line purpose, and the page's main actions on the right. */
export function PageHeader({ title, description, icon: Icon, actions, className }: {
  title: string
  description?: React.ReactNode
  icon?: React.ComponentType<{ className?: string }>
  actions?: React.ReactNode
  className?: string
}) {
  return (
    <header className={cn("flex items-end justify-between gap-6 pb-6", className)}>
      <div className="flex items-start gap-3 min-w-0">
        {Icon && (
          <div className="mt-0.5 grid size-10 shrink-0 place-items-center rounded-xl bg-accent text-accent-foreground">
            <Icon className="size-5" />
          </div>
        )}
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          {description && <p className="mt-1 text-sm text-muted-foreground max-w-2xl">{description}</p>}
        </div>
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </header>
  )
}

/** Scrollable page body with standard gutters and a readable max width. */
export function PageBody({ children, className, wide }: { children: React.ReactNode; className?: string; wide?: boolean }) {
  return (
    <div className="h-full overflow-y-auto">
      <div className={cn("mx-auto px-8 py-8", wide ? "max-w-7xl" : "max-w-5xl", className)}>{children}</div>
    </div>
  )
}

/** A titled group of related controls. */
export function Section({ title, description, actions, children, className }: {
  title: string
  description?: React.ReactNode
  actions?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <section className={cn("rounded-2xl border bg-card text-card-foreground shadow-xs", className)}>
      <div className="flex items-start justify-between gap-4 border-b px-6 py-4">
        <div>
          <h2 className="text-base font-semibold">{title}</h2>
          {description && <p className="mt-0.5 text-[13px] text-muted-foreground">{description}</p>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      <div className="px-6 py-5">{children}</div>
    </section>
  )
}

export type Tone = "ok" | "busy" | "warn" | "error" | "off" | "live"

const toneClass: Record<Tone, string> = {
  ok: "bg-success",
  busy: "bg-primary animate-pulse",
  warn: "bg-warning",
  error: "bg-destructive",
  off: "bg-muted-foreground/40",
  live: "bg-live animate-pulse",
}

/** Small colored dot + text; color is never the only signal. */
export function StatusDot({ tone, label, className }: { tone: Tone; label?: React.ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs", className)}>
      <span className={cn("size-2 shrink-0 rounded-full", toneClass[tone])} aria-hidden />
      {label}
    </span>
  )
}

/** A thin real progress bar (value 0-100) or an indeterminate one when value is undefined. */
export function ProgressBar({ value, className }: { value?: number; className?: string }) {
  return (
    <div className={cn("relative h-1.5 w-full overflow-hidden rounded-full bg-muted", className)}
      role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={value}>
      {value === undefined ? (
        <div className="absolute inset-y-0 w-1/3 animate-[indeterminate_1.2s_ease-in-out_infinite] rounded-full bg-primary" />
      ) : (
        <div className="h-full rounded-full bg-primary transition-[width] duration-300" style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
      )}
    </div>
  )
}

/** Dot-meter for qualitative ratings (speed, quality). */
export function Meter({ value, max = 5, label }: { value: number; max?: number; label: string }) {
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground" aria-label={`${label}: ${value} of ${max}`}>
      <span className="w-12">{label}</span>
      <span className="flex gap-0.5">
        {Array.from({ length: max }).map((_, i) => (
          <span key={i} className={cn("h-1.5 w-3 rounded-full", i < value ? "bg-primary" : "bg-muted")} />
        ))}
      </span>
    </div>
  )
}
