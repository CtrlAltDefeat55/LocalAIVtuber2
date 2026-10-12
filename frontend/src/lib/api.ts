import { toast } from "sonner"

/** Extract a readable message from a failed fetch response (JSON {error} or plain text). */
export async function readError(res: Response): Promise<string> {
  try {
    const text = await res.text()
    try {
      const data = JSON.parse(text)
      return data.error || data.detail || data.message || `Request failed (${res.status})`
    } catch {
      return text.slice(0, 300) || `Request failed (${res.status})`
    }
  } catch {
    return `Request failed (${res.status})`
  }
}

/** fetch + JSON with errors thrown as Error(message from the server). */
export async function api<T = unknown>(url: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init || {}
  const res = await fetch(url, {
    ...rest,
    headers: json !== undefined ? { "Content-Type": "application/json", ...(rest.headers || {}) } : rest.headers,
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  })
  if (!res.ok) throw new Error(await readError(res))
  const type = res.headers.get("content-type") || ""
  return (type.includes("application/json") ? res.json() : res.text()) as Promise<T>
}

/** Navigate the app shell to another page (handled in mainpage.tsx). */
export function goToPage(page: string) {
  window.dispatchEvent(new CustomEvent("lav:navigate", { detail: page }))
}

const recentToasts = new Map<string, number>()
/** Show an error toast, but not the same message more than once every few seconds. */
export function toastErrorOnce(message: string, action?: { label: string; page: string }) {
  const now = Date.now()
  if ((recentToasts.get(message) ?? 0) > now - 8000) return
  recentToasts.set(message, now)
  toast.error(message, action ? { action: { label: action.label, onClick: () => goToPage(action.page) } } : undefined)
}

export function formatBytes(bytes?: number | null): string {
  if (!bytes) return "0 B"
  const units = ["B", "KB", "MB", "GB", "TB"]
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / Math.pow(1024, i)).toFixed(i >= 3 ? 2 : 1)} ${units[i]}`
}

export function formatDuration(seconds?: number | null): string {
  if (seconds == null || !isFinite(seconds)) return "--"
  if (seconds < 60) return `${Math.round(seconds)}s`
  const m = Math.floor(seconds / 60)
  if (m < 60) return `${m}m ${Math.round(seconds % 60)}s`
  return `${Math.floor(m / 60)}h ${m % 60}m`
}
