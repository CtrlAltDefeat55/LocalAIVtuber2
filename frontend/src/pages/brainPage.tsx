import { useCallback, useEffect, useMemo, useState } from "react"
import { Brain, Check, Download, FolderOpen, Loader2, MoreHorizontal, Plus, Power, RotateCcw, Search, Trash2, TriangleAlert, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { PageBody, PageHeader, ProgressBar, Section, StatusDot } from "@/components/layout"
import SettingSwitch from "@/components/setting-switch"
import SettingSlider from "@/components/setting-slider"
import SettingTextbox from "@/components/setting-textbox"
import { useConfirm } from "@/components/confirm-dialog"
import { useSettings } from "@/context/SettingsContext"
import { useSystemStatus } from "@/context/SystemStatusContext"
import { api, formatBytes, formatDuration } from "@/lib/api"
import { cn } from "@/lib/utils"

interface DownloadInfo {
  id: string
  status: "starting" | "downloading" | "completed" | "error" | "cancelled"
  progress: number
  downloaded_size: number
  total_size: number
  speed_bps: number
  eta_seconds: number | null
  error: string | null
  current_file: string
}

interface ModelInfo {
  id: string
  displayName: string
  description?: string
  fileName?: string
  file_exists: boolean
  file_size_readable?: string
  size_hint?: string
  vram_hint?: string
  tags?: string[]
  recommended?: boolean
  vision?: boolean
  mmproj_exists?: boolean
  downloadable: boolean
  custom?: boolean
  local_only?: boolean
  download: DownloadInfo | null
}

interface ModelsResponse {
  models: ModelInfo[]
  currentModel: ModelInfo | null
}

const SAMPLING_DEFAULTS: Record<string, number> = {
  "llm.temperature": 0.8, "llm.top_p": 0.95, "llm.top_k": 40, "llm.min_p": 0.05, "llm.repeat_penalty": 1.1,
}

export default function BrainPage({ isActive }: { isActive: boolean }) {
  const [models, setModels] = useState<ModelInfo[]>([])
  const [currentId, setCurrentId] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [addOpen, setAddOpen] = useState(false)
  const { status, refresh } = useSystemStatus()
  const { settings, updateSetting } = useSettings()
  const { confirm, dialog } = useConfirm()

  const load = useCallback(async () => {
    try {
      const data = await api<ModelsResponse>("/api/llm/models")
      setModels(data.models)
      setCurrentId(data.currentModel?.id ?? null)
    } catch (e) {
      console.error(e)
    }
  }, [])

  const anyDownloading = models.some((m) => m.download && ["starting", "downloading"].includes(m.download.status))

  useEffect(() => {
    if (!isActive) return
    load()
    const timer = setInterval(load, anyDownloading ? 1000 : 6000)
    return () => clearInterval(timer)
  }, [isActive, load, anyDownloading])

  const current = useMemo(() => models.find((m) => m.id === currentId) ?? null, [models, currentId])
  const llm = status?.llm

  const run = async (key: string, fn: () => Promise<unknown>, success?: string) => {
    setBusy(key)
    try {
      await fn()
      if (success) toast.success(success)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(null)
      await load()
      refresh()
    }
  }

  const download = (m: ModelInfo) =>
    run(`dl:${m.id}`, () => api("/api/llm/models/download", { method: "POST", json: { model_id: m.id } }))

  const cancel = (m: ModelInfo) =>
    m.download && run(`cancel:${m.id}`, () => api(`/api/llm/models/download/${m.download!.id}`, { method: "DELETE" }), "Download cancelled")

  const select = (m: ModelInfo) =>
    run(`use:${m.id}`, async () => {
      await updateSetting("llm.model_id", m.id, { immediate: true })
      setCurrentId(m.id)
    }, settings["llm.keep_model_loaded"] !== false ? `Loading ${m.displayName}…` : `${m.displayName} selected`)

  const remove = async (m: ModelInfo) => {
    const ok = await confirm({
      title: m.custom ? `Remove ${m.displayName}?` : `Delete ${m.displayName} files?`,
      description: m.custom
        ? "The downloaded files and this entry are removed from your computer."
        : `This frees ${m.file_size_readable ?? "the disk space"}. You can download it again later.`,
      confirmLabel: m.custom ? "Remove model" : "Delete files",
    })
    if (ok) run(`del:${m.id}`, () => api("/api/llm/models/delete", { method: "DELETE", json: { model_id: m.id } }), "Model files deleted")
  }

  const openFolder = () => api("/api/system/open-folder", { method: "POST", json: { which: "models" } })
    .catch((e) => toast.error((e as Error).message))

  const visionAvailable = Boolean(current?.mmproj_exists)

  return (
    <PageBody>
      <PageHeader
        icon={Brain}
        title="Brain"
        description="The language model your VTuber thinks with. Everything runs on this computer; models are downloaded once and kept in the app folder."
        actions={<>
          <Button variant="outline" onClick={openFolder}><FolderOpen /> Models folder</Button>
          <Button variant="outline" onClick={() => setAddOpen(true)}><Plus /> Add from Hugging Face</Button>
        </>}
      />

      {/* Current model + runtime state */}
      <div className="mb-6 rounded-2xl border bg-card p-5 shadow-xs">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="min-w-0">
            <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Active model</div>
            <div className="mt-1 flex items-center gap-3">
              <span className="truncate text-lg font-semibold">{current?.displayName ?? "None selected"}</span>
              {llm && (
                <StatusDot
                  tone={llm.state === "ready" ? "ok" : llm.state === "loading" ? "busy" : llm.state === "error" ? "error" : "off"}
                  label={<span className="text-muted-foreground">{
                    !llm.model_downloaded ? "Not downloaded" :
                      llm.state === "ready" ? (llm.vision_active ? "Ready · vision on" : "Ready") :
                        llm.state === "loading" ? "Loading into memory…" :
                          llm.state === "error" ? "Failed to load" : "Not loaded (loads on first message)"}</span>}
                />
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {llm?.state === "ready" || llm?.state === "loading" ? (
              <Button variant="outline" disabled={busy === "unload"}
                onClick={() => run("unload", () => api("/api/llm/unload", { method: "POST" }), "Model unloaded, GPU memory freed")}>
                <Power /> Unload
              </Button>
            ) : (
              <Button disabled={!current?.file_exists || busy === "load"}
                onClick={() => run("load", () => api("/api/llm/load", { method: "POST" }))}>
                {busy === "load" ? <Loader2 className="animate-spin" /> : <Power />} Load now
              </Button>
            )}
          </div>
        </div>
        {llm?.state === "loading" && <ProgressBar className="mt-4" />}
        {llm && !llm.runtime_installed && (
          <Alert tone="error" title="The LLM runtime (llama-server) is missing">
            Run the start script again; it downloads the right runtime for your GPU automatically.
          </Alert>
        )}
        {llm?.state === "error" && llm.error && (
          <Alert tone="error" title="The model could not be loaded">
            <pre className="whitespace-pre-wrap break-words font-sans">{llm.error}</pre>
          </Alert>
        )}
      </div>

      {/* Library */}
      <div className="mb-3 flex items-end justify-between">
        <div>
          <h2 className="text-base font-semibold">Model library</h2>
          <p className="text-[13px] text-muted-foreground">Bigger models talk better but need more GPU memory. If a model does not fit, it still runs but replies start slower.</p>
        </div>
      </div>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {models.map((m) => {
          const dl = m.download
          const downloading = dl && ["starting", "downloading"].includes(dl.status)
          const isCurrent = m.id === currentId
          return (
            <div key={m.id} className={cn("flex flex-col rounded-2xl border bg-card p-4 shadow-xs transition-colors",
              isCurrent && "border-primary/60 ring-1 ring-primary/30")}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="truncate font-semibold">{m.displayName}</h3>
                    {isCurrent && <Badge className="bg-primary/15 text-primary border-primary/30" variant="outline"><Check /> {m.file_exists ? "In use" : "Selected"}</Badge>}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {(m.tags ?? []).map((t) => (
                      <Badge key={t} variant="outline" className={cn("text-[11px]", t === "Recommended" && "border-primary/40 text-primary")}>{t}</Badge>
                    ))}
                  </div>
                </div>
                {(m.file_exists || m.custom) && (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" size="icon" aria-label={`More actions for ${m.displayName}`}><MoreHorizontal /></Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem variant="destructive" onClick={() => remove(m)}>
                        <Trash2 /> {m.custom ? "Remove model" : "Delete files"}
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                )}
              </div>
              {m.description && <p className="mt-2 text-[13px] leading-snug text-muted-foreground">{m.description}</p>}
              <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground tabular">
                <span>Size: <span className="text-foreground">{m.file_exists ? m.file_size_readable : (m.size_hint ?? "unknown")}</span></span>
                {m.vram_hint && <span>GPU: <span className="text-foreground">{m.vram_hint}</span></span>}
                {m.vision && <span>Vision: <span className="text-foreground">{m.mmproj_exists ? "included" : "supported"}</span></span>}
              </div>

              <div className="mt-auto pt-4">
                {downloading ? (
                  <div className="space-y-2">
                    <ProgressBar value={dl!.total_size ? dl!.progress : undefined} />
                    <div className="flex items-center justify-between text-xs text-muted-foreground tabular">
                      <span>{formatBytes(dl!.downloaded_size)} / {dl!.total_size ? formatBytes(dl!.total_size) : "…"} · {formatBytes(dl!.speed_bps)}/s · {formatDuration(dl!.eta_seconds)} left</span>
                      <Button variant="ghost" size="sm" onClick={() => cancel(m)}><X /> Cancel</Button>
                    </div>
                  </div>
                ) : m.file_exists ? (
                  <Button className="w-full" variant={isCurrent ? "secondary" : "default"} disabled={isCurrent || busy === `use:${m.id}`} onClick={() => select(m)}>
                    {isCurrent ? <><Check /> Selected</> : busy === `use:${m.id}` ? <><Loader2 className="animate-spin" /> Switching…</> : "Use this model"}
                  </Button>
                ) : m.downloadable ? (
                  <div className="space-y-2">
                    {dl?.status === "error" && <p className="text-xs text-destructive">Download failed: {dl.error} — click Download to resume.</p>}
                    <Button className="w-full" variant="outline" disabled={busy === `dl:${m.id}`} onClick={() => download(m)}>
                      {busy === `dl:${m.id}` ? <Loader2 className="animate-spin" /> : <Download />} Download {m.size_hint ? `(${m.size_hint})` : ""}
                    </Button>
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground">File missing from the Models folder.</p>
                )}
              </div>
            </div>
          )
        })}
      </div>

      <div className="mt-8 space-y-6">
        <Section title="Personality" description="Who your VTuber is. Sent with every message.">
          <div className="space-y-5">
            <SettingTextbox id="llm.system_prompt" label="Character prompt" rows={5}
              placeholder="You are Aya, a cheerful VTuber who loves games. Keep replies short and spoken-style." />
            <SettingSwitch id="llm.enableMemoryRetrieval" label="Use long-term memory"
              description="Look up related moments from past chats (indexed on the Memory page) and give them to the model." />
          </div>
        </Section>

        <Section title="Performance" description="Changing these restarts the model (a few seconds to a minute).">
          <div className="grid grid-cols-1 gap-x-10 gap-y-5 md:grid-cols-2">
            <div className="space-y-2">
              <Label className="text-sm font-medium">Memory window (context)</Label>
              <Select value={String(settings["llm.context_size"] ?? 8192)} onValueChange={(v) => updateSetting("llm.context_size", Number(v), { immediate: true })}>
                <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {[4096, 8192, 16384, 32768].map((n) => (
                    <SelectItem key={n} value={String(n)}>{n.toLocaleString()} tokens{n === 8192 ? " (recommended)" : ""}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">How much recent conversation the model remembers. Larger uses more GPU memory.</p>
            </div>
            <div className="space-y-2">
              <Label className="text-sm font-medium" htmlFor="gpu-layers">GPU layers</Label>
              <div className="flex gap-2">
                <Select value={settings["llm.gpu_layers"] && settings["llm.gpu_layers"] !== "auto" ? "manual" : "auto"}
                  onValueChange={(v) => updateSetting("llm.gpu_layers", v === "auto" ? "auto" : "99", { immediate: true })}
                  disabled={Boolean(settings["load-llm-cpu"])}>
                  <SelectTrigger className="w-36"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="auto">Auto-fit</SelectItem>
                    <SelectItem value="manual">Manual</SelectItem>
                  </SelectContent>
                </Select>
                {settings["llm.gpu_layers"] && settings["llm.gpu_layers"] !== "auto" && !settings["load-llm-cpu"] && (
                  <GpuLayersInput value={String(settings["llm.gpu_layers"])} onCommit={(v) => updateSetting("llm.gpu_layers", v, { immediate: true })} />
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                {settings["load-llm-cpu"] ? "Disabled while “Run on CPU only” is on." : "Auto-fit puts as much of the model on the GPU as fits. Use Manual only to leave VRAM for other apps."}
              </p>
            </div>
            <SettingSlider id="llm.max_tokens" label="Max reply length" unit="tok" min={64} max={2048} step={32} defaultValue={512}
              description="Upper limit for one reply. Short replies keep the stream snappy." />
            <div className="space-y-3">
              <SettingSwitch id="llm.keep_model_loaded" label="Keep model loaded"
                description="Fastest replies. Turn off to free GPU memory after every reply (much slower)." />
              <SettingSwitch id="load-llm-cpu" label="Run on CPU only"
                description="For computers without a supported GPU. Works, but replies are slow." />
              <SettingSwitch id="llm.enable_vision" label="Vision (see the screen)"
                description="Lets the model look at screenshots. Uses about 1 GB extra GPU memory."
                disabled={!visionAvailable}
                disabledReason={current?.vision ? "Download this model again to get its vision files." : "The selected model has no vision support."} />
              <SettingSwitch id="llm.thinking" label="Think before answering"
                description="Better reasoning on hard questions, but adds a long pause before speaking. Off is best for streaming." />
            </div>
          </div>
        </Section>

        <Collapsible>
          <Section title="Sampling" description="Fine-tune how creative or predictable replies are."
            actions={<>
              <Button variant="ghost" size="sm" onClick={() => {
                Object.entries(SAMPLING_DEFAULTS).forEach(([k, v]) => updateSetting(k, v))
                updateSetting("llm.seed", -1)
                toast.success("Sampling reset to defaults")
              }}><RotateCcw /> Reset</Button>
              <CollapsibleTrigger asChild><Button variant="outline" size="sm">Show / hide</Button></CollapsibleTrigger>
            </>}>
            <CollapsibleContent>
              <div className="grid grid-cols-1 gap-x-10 gap-y-6 md:grid-cols-2">
                <SettingSlider id="llm.temperature" label="Temperature" min={0.1} max={2} step={0.01} defaultValue={0.8}
                  description="Higher = more surprising and creative; lower = more focused." />
                <SettingSlider id="llm.top_p" label="Top P" min={0.01} max={1} step={0.01} defaultValue={0.95}
                  description="Only consider the most likely words that add up to this probability." />
                <SettingSlider id="llm.top_k" label="Top K" min={1} max={100} step={1} defaultValue={40}
                  description="Only consider the K most likely next words." />
                <SettingSlider id="llm.min_p" label="Min P" min={0} max={0.5} step={0.01} defaultValue={0.05}
                  description="Ignore words less likely than this fraction of the best word." />
                <SettingSlider id="llm.repeat_penalty" label="Repeat penalty" min={0.5} max={2} step={0.01} defaultValue={1.1}
                  description="Higher discourages repeating the same phrases." />
                <SeedInput />
              </div>
            </CollapsibleContent>
          </Section>
        </Collapsible>
      </div>

      <AddFromHFDialog open={addOpen} onOpenChange={setAddOpen} onAdded={load} />
      {dialog}
    </PageBody>
  )
}

function Alert({ tone, title, children }: { tone: "error" | "warn"; title: string; children: React.ReactNode }) {
  return (
    <div className={cn("mt-4 flex gap-3 rounded-xl border p-3 text-sm",
      tone === "error" ? "border-destructive/40 bg-destructive/10" : "border-warning/40 bg-warning/10")}>
      <TriangleAlert className={cn("mt-0.5 size-4 shrink-0", tone === "error" ? "text-destructive" : "text-warning")} />
      <div className="min-w-0 space-y-1">
        <div className="font-medium">{title}</div>
        <div className="text-[13px] text-muted-foreground">{children}</div>
      </div>
    </div>
  )
}

function GpuLayersInput({ value, onCommit }: { value: string; onCommit: (v: string) => void }) {
  const [draft, setDraft] = useState(value)
  useEffect(() => setDraft(value), [value])
  const commit = () => {
    const n = parseInt(draft, 10)
    if (Number.isFinite(n) && n >= 0 && n <= 999) onCommit(String(n))
    else setDraft(value)
  }
  return (
    <Input id="gpu-layers" className="w-24 tabular" inputMode="numeric" value={draft} aria-label="Number of GPU layers"
      onChange={(e) => setDraft(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === "Enter" && commit()} />
  )
}

function SeedInput() {
  const { settings, updateSetting } = useSettings()
  const value = settings["llm.seed"] ?? -1
  const [draft, setDraft] = useState(String(value))
  useEffect(() => setDraft(String(value)), [value])
  const commit = () => {
    const n = parseInt(draft, 10)
    if (Number.isFinite(n) && n >= -1) updateSetting("llm.seed", n)
    else setDraft(String(value))
  }
  return (
    <div className="space-y-2">
      <Label htmlFor="llm-seed" className="text-sm font-medium">Seed</Label>
      <Input id="llm-seed" className="w-40 tabular" inputMode="numeric" value={draft}
        onChange={(e) => setDraft(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === "Enter" && commit()} />
      <p className="text-xs text-muted-foreground">-1 = random each time. A fixed number repeats the same reply for the same input.</p>
    </div>
  )
}

interface HFFile { path: string; size: number }

function AddFromHFDialog({ open, onOpenChange, onAdded }: { open: boolean; onOpenChange: (o: boolean) => void; onAdded: () => void }) {
  const [repo, setRepo] = useState("")
  const [files, setFiles] = useState<HFFile[] | null>(null)
  const [projs, setProjs] = useState<HFFile[]>([])
  const [file, setFile] = useState<string>("")
  const [mmproj, setMmproj] = useState<string>("none")
  const [name, setName] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) { setFiles(null); setError(null); setFile(""); setMmproj("none"); setName("") }
  }, [open])

  const find = async () => {
    setLoading(true); setError(null); setFiles(null)
    try {
      const data = await api<{ repo: string; files: HFFile[]; mmproj: HFFile[] }>("/api/llm/models/hf/files", { method: "POST", json: { repo } })
      setRepo(data.repo)
      setFiles(data.files)
      setProjs(data.mmproj)
      const preferred = data.files.find((f) => /q4_k_m/i.test(f.path)) ?? data.files[0]
      setFile(preferred?.path ?? "")
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const add = async () => {
    setLoading(true); setError(null)
    try {
      await api("/api/llm/models/add-hf", {
        method: "POST",
        json: { repo, file, mmproj: mmproj === "none" ? null : mmproj, displayName: name || null },
      })
      toast.success("Download started. Track it in the model library.")
      onOpenChange(false)
      onAdded()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Add a model from Hugging Face</DialogTitle>
          <DialogDescription>Any GGUF model works, e.g. <code className="text-xs">unsloth/gemma-4-12b-it-GGUF</code>. Pick the quant that fits your GPU (Q4_K_M is a good default).</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="flex gap-2">
            <Input autoFocus placeholder="owner/model-GGUF or a huggingface.co link" value={repo}
              onChange={(e) => setRepo(e.target.value)} onKeyDown={(e) => e.key === "Enter" && repo.trim() && find()} />
            <Button variant="outline" onClick={find} disabled={!repo.trim() || loading}>
              {loading && !files ? <Loader2 className="animate-spin" /> : <Search />} Find files
            </Button>
          </div>
          {files && (
            <>
              <div className="space-y-2">
                <Label>Model file</Label>
                <div className="max-h-56 overflow-y-auto rounded-lg border">
                  {files.map((f) => (
                    <label key={f.path} className={cn("flex cursor-pointer items-center justify-between gap-3 border-b px-3 py-2 text-sm last:border-b-0 hover:bg-accent/50",
                      file === f.path && "bg-accent")}>
                      <span className="flex min-w-0 items-center gap-2">
                        <input type="radio" name="hf-file" className="accent-[var(--primary)]" checked={file === f.path} onChange={() => setFile(f.path)} />
                        <span className="truncate font-mono text-xs">{f.path}</span>
                      </span>
                      <span className="shrink-0 text-xs text-muted-foreground tabular">{formatBytes(f.size)}</span>
                    </label>
                  ))}
                </div>
              </div>
              {projs.length > 0 && (
                <div className="space-y-2">
                  <Label>Vision projector (optional)</Label>
                  <Select value={mmproj} onValueChange={setMmproj}>
                    <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">Don't download (text only)</SelectItem>
                      {projs.map((p) => <SelectItem key={p.path} value={p.path}>{p.path} ({formatBytes(p.size)})</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
              )}
              <div className="space-y-2">
                <Label htmlFor="hf-name">Display name (optional)</Label>
                <Input id="hf-name" value={name} onChange={(e) => setName(e.target.value)} placeholder={file.split("/").pop()?.replace(/\.gguf$/i, "")} />
              </div>
            </>
          )}
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={add} disabled={!files || !file || loading}>
            {loading && files ? <Loader2 className="animate-spin" /> : <Download />} Download model
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
