import { useCallback, useEffect, useRef, useState } from "react"
import { AudioLines, Check, Download, FileAudio, FolderOpen, KeyRound, Loader2, MoreHorizontal, Pause, Pencil, Play, Plus, Power, Square, Terminal, Trash2, TriangleAlert, Upload, Volume2, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Slider } from "@/components/ui/slider"
import { Meter, PageBody, PageHeader, ProgressBar, Section, StatusDot, Tone } from "@/components/layout"
import { useConfirm } from "@/components/confirm-dialog"
import RvcSettings from "@/components/rvc-settings"
import { useSettings } from "@/context/SettingsContext"
import { useSystemStatus } from "@/context/SystemStatusContext"
import { api, goToPage, readError } from "@/lib/api"
import { ttsManager } from "@/lib/ttsManager"
import { RVCProvider } from "@/lib/tts/rvcProvider"
import { cn } from "@/lib/utils"

type EngineState = "not_installed" | "installing" | "stopped" | "starting" | "ready" | "error"

interface Engine {
  id: string
  label: string
  summary: string
  languages: string[]
  speed: number
  quality: number
  vram: string
  min_ref_seconds: number
  recommended?: boolean
  variants?: Record<string, string>
  needs_token?: string
  has_token?: boolean | null
  state: EngineState
  installed: boolean
  error: string | null
  step: string | null
  variant: string | null
  log: string[]
}

interface EnginesResponse {
  active_engine: string
  current_voice: string | null
  engines: Engine[]
  gpu: { kind: string; name?: string }
  options: { speed?: number }
}

interface Voice {
  name: string
  reference_text: string
  language: string
  duration: number | null
}

const LANGUAGES: Record<string, string> = {
  en: "English", ja: "Japanese", zh: "Chinese", ko: "Korean", yue: "Cantonese",
  es: "Spanish", fr: "French", de: "German", pt: "Portuguese", it: "Italian", ru: "Russian", other: "Other",
}

const SPEED_ENGINES = new Set(["omnivoice", "luxtts", "gptsovits"])

function engineTone(state: EngineState): [Tone, string] {
  switch (state) {
    case "ready": return ["ok", "Running"]
    case "starting": return ["busy", "Starting (first start downloads the voice model)…"]
    case "installing": return ["busy", "Installing…"]
    case "error": return ["error", "Error"]
    case "stopped": return ["off", "Installed"]
    default: return ["off", "Not installed"]
  }
}

export default function TTSPage({ isActive }: { isActive: boolean }) {
  const [data, setData] = useState<EnginesResponse | null>(null)
  const [voices, setVoices] = useState<Voice[]>([])
  const [currentVoice, setCurrentVoice] = useState<string | null>(null)
  const [voiceDialog, setVoiceDialog] = useState<{ mode: "add" } | { mode: "edit"; voice: Voice } | null>(null)
  const [logFor, setLogFor] = useState<string | null>(null)
  const [rvcAvailable, setRvcAvailable] = useState(false)
  const { settings, updateSetting } = useSettings()
  const { refresh: refreshStatus } = useSystemStatus()
  const { confirm, dialog } = useConfirm()
  const provider = settings["tts.provider"] === "rvc" ? "rvc" : "local"

  const loadEngines = useCallback(async () => {
    try { setData(await api<EnginesResponse>("/api/tts/engines")) } catch (e) { console.error(e) }
  }, [])
  const loadVoices = useCallback(async () => {
    try {
      const v = await api<{ library: Voice[]; current_voice: string | null }>("/api/tts/voices")
      setVoices(v.library)
      setCurrentVoice(v.current_voice)
    } catch (e) { console.error(e) }
  }, [])

  const busy = data?.engines.some((e) => e.state === "installing" || e.state === "starting")
  useEffect(() => {
    if (!isActive) return
    loadEngines(); loadVoices()
    const rvc = ttsManager.getProvider<RVCProvider>("rvc")
    setRvcAvailable(rvc.isAvailable())
    const unsub = rvc.subscribe(() => setRvcAvailable(rvc.isAvailable()))
    const timer = setInterval(loadEngines, busy ? 1500 : 5000)
    return () => { clearInterval(timer); unsub() }
  }, [isActive, busy, loadEngines, loadVoices])

  const act = async (fn: () => Promise<unknown>, success?: string) => {
    try {
      await fn()
      if (success) toast.success(success)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      loadEngines(); refreshStatus()
    }
  }

  const activate = (engine: Engine, variant?: string) => act(async () => {
    await api(`/api/tts/engines/${engine.id}/activate`, { method: "POST", json: { variant: variant ?? engine.variant ?? null } })
    if (provider !== "local") await updateSetting("tts.provider", "local", { immediate: true })
  }, `${engine.label} selected. It starts in the background.`)

  const uninstall = async (engine: Engine) => {
    const ok = await confirm({
      title: `Uninstall ${engine.label}?`,
      description: "Removes its Python environment (a few GB). Downloaded voice model weights stay in the cache so a reinstall is quick. Your voices are not affected.",
      confirmLabel: "Uninstall",
    })
    if (ok) act(() => api(`/api/tts/engines/${engine.id}/uninstall`, { method: "POST" }), `${engine.label} uninstalled`)
  }

  const selectVoice = async (name: string) => {
    setCurrentVoice(name)
    try {
      await api("/api/tts/change-voice", { method: "POST", json: { voice_name: name } })
    } catch (e) {
      toast.error((e as Error).message)
      loadVoices()
    }
  }

  const deleteVoice = async (voice: Voice) => {
    const ok = await confirm({
      title: `Delete voice “${voice.name}”?`,
      description: "The reference recording and transcript are removed. This cannot be undone.",
      confirmLabel: "Delete voice",
    })
    if (!ok) return
    try {
      await api("/api/tts/delete", { method: "DELETE", json: { name: voice.name } })
      toast.success(`Deleted ${voice.name}`)
    } catch (e) {
      toast.error((e as Error).message)
    }
    loadVoices()
  }

  const active = data?.engines.find((e) => e.id === data.active_engine)
  const minRef = provider === "local" ? active?.min_ref_seconds ?? 0 : 0

  return (
    <PageBody>
      <PageHeader icon={AudioLines} title="Voice"
        description="Pick how your VTuber sounds: a voice engine plus a short reference recording to clone. Engines install with one click and run on this computer."
        actions={<Button variant="outline" onClick={() => api("/api/system/open-folder", { method: "POST", json: { which: "voices" } }).catch((e) => toast.error(e.message))}>
          <FolderOpen /> Voices folder
        </Button>}
      />

      <VoiceTester engineLabel={provider === "rvc" ? "RVC" : active?.label} voice={currentVoice} />

      <Section className="mt-6" title="Voice engine"
        description={data ? `Detected: ${data.gpu.kind === "cuda" ? `NVIDIA GPU${data.gpu.name ? ` (${data.gpu.name})` : ""}` : data.gpu.kind === "mps" ? "Apple Silicon GPU" : "no supported GPU (CPU mode)"}. Speed matters most for live chat; Chatterbox Turbo is the best balance, LuxTTS the fastest.` : undefined}>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {data?.engines.map((engine) => {
            const isActive = provider === "local" && data.active_engine === engine.id
            const [tone, label] = engineTone(engine.state)
            return (
              <div key={engine.id} className={cn("flex flex-col rounded-xl border p-4 transition-colors",
                isActive ? "border-primary/60 bg-primary/5 ring-1 ring-primary/30" : "bg-background/40")}>
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <h3 className="font-semibold">{engine.label}</h3>
                      {engine.recommended && <Badge variant="outline" className="border-primary/40 text-primary text-[11px]">Recommended</Badge>}
                      {isActive && <Badge variant="outline" className="bg-primary/15 text-primary border-primary/30 text-[11px]"><Check /> Active</Badge>}
                    </div>
                    <StatusDot className="mt-1" tone={tone} label={<span className="text-muted-foreground">{engine.state === "installing" ? engine.step ?? label : label}</span>} />
                  </div>
                  {(engine.installed || engine.log.length > 0) && (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" aria-label={`More actions for ${engine.label}`}><MoreHorizontal /></Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => setLogFor(engine.id)}><Terminal /> Show log</DropdownMenuItem>
                        {engine.state === "ready" && (
                          <DropdownMenuItem onClick={() => act(() => api(`/api/tts/engines/${engine.id}/stop`, { method: "POST" }), `${engine.label} stopped`)}>
                            <Square /> Stop (free GPU memory)
                          </DropdownMenuItem>
                        )}
                        {engine.installed && (
                          <>
                            <DropdownMenuItem onClick={() => act(() => api(`/api/tts/engines/${engine.id}/install`, { method: "POST" }))}>
                              <Download /> Repair / update
                            </DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem variant="destructive" onClick={() => uninstall(engine)}><Trash2 /> Uninstall</DropdownMenuItem>
                          </>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  )}
                </div>
                <p className="mt-2 text-[13px] leading-snug text-muted-foreground">{engine.summary}</p>
                <div className="mt-3 grid grid-cols-2 gap-1">
                  <Meter label="Speed" value={engine.speed} />
                  <Meter label="Quality" value={engine.quality} />
                </div>
                <div className="mt-2 flex flex-wrap gap-x-4 text-xs text-muted-foreground">
                  <span>GPU: <span className="text-foreground">{engine.vram}</span></span>
                  <span>Languages: <span className="text-foreground">{engine.languages.join(", ")}</span></span>
                </div>
                {engine.variants && (
                  <div className="mt-3 flex items-center gap-2">
                    <Label className="text-xs">Model size</Label>
                    <Select value={engine.variant ?? Object.keys(engine.variants)[0]} onValueChange={(v) => activate(engine, v)}>
                      <SelectTrigger size="sm" className="h-8 w-60"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {Object.entries(engine.variants).map(([k, v]) => <SelectItem key={k} value={k}>{v}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                )}
                {engine.needs_token && !engine.has_token && (
                  <div className="mt-3 flex gap-2 rounded-lg border border-warning/40 bg-warning/10 p-2.5 text-xs">
                    <KeyRound className="mt-0.5 size-3.5 shrink-0 text-warning" />
                    <div>
                      {engine.needs_token}{" "}
                      <button className="font-medium text-primary underline-offset-2 hover:underline" onClick={() => goToPage("settings")}>Add token</button>
                    </div>
                  </div>
                )}
                {engine.error && (
                  <div className="mt-3 flex gap-2 rounded-lg border border-destructive/40 bg-destructive/10 p-2.5 text-xs">
                    <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-destructive" />
                    <pre className="max-h-28 overflow-auto whitespace-pre-wrap break-words font-sans">{engine.error}</pre>
                  </div>
                )}
                <div className="mt-auto pt-4">
                  {engine.state === "installing" ? (
                    <div className="space-y-2">
                      <ProgressBar />
                      <div className="flex justify-between">
                        <Button variant="ghost" size="sm" onClick={() => setLogFor(engine.id)}><Terminal /> Details</Button>
                        <Button variant="ghost" size="sm" onClick={() => act(() => api(`/api/tts/engines/${engine.id}/cancel`, { method: "POST" }))}><X /> Cancel</Button>
                      </div>
                    </div>
                  ) : !engine.installed ? (
                    <Button className="w-full" variant="outline" onClick={() => act(() => api(`/api/tts/engines/${engine.id}/install`, { method: "POST" }),
                      `Installing ${engine.label}. This downloads a few GB and can take several minutes.`)}>
                      <Download /> Install
                    </Button>
                  ) : isActive ? (
                    engine.state === "stopped" || engine.state === "error" ? (
                      <Button className="w-full" onClick={() => activate(engine)}><Power /> Start</Button>
                    ) : (
                      <Button className="w-full" variant="secondary" disabled>
                        {engine.state === "starting" ? <><Loader2 className="animate-spin" /> Starting…</> : <><Check /> In use</>}
                      </Button>
                    )
                  ) : (
                    <Button className="w-full" onClick={() => activate(engine)}>Use this engine</Button>
                  )}
                </div>
              </div>
            )
          })}
          {rvcAvailable && (
            <div className={cn("flex flex-col rounded-xl border p-4", provider === "rvc" ? "border-primary/60 bg-primary/5 ring-1 ring-primary/30" : "bg-background/40")}>
              <h3 className="font-semibold">RVC voice conversion</h3>
              <p className="mt-2 text-[13px] text-muted-foreground">Edge TTS voice converted with an RVC model (from the classic Windows package).</p>
              <div className="mt-auto pt-4">
                {provider === "rvc"
                  ? <Button className="w-full" variant="secondary" disabled><Check /> In use</Button>
                  : <Button className="w-full" onClick={() => updateSetting("tts.provider", "rvc", { immediate: true })}>Use RVC</Button>}
              </div>
            </div>
          )}
        </div>
        {provider === "rvc" && <div className="mt-4"><RvcSettings /></div>}
      </Section>

      <Section className="mt-6" title="Voice library"
        description="Reference recordings to clone. Every engine uses the same library. Best results: 6–15 seconds of clean speech, no music or echo, plus the exact words spoken."
        actions={<Button onClick={() => setVoiceDialog({ mode: "add" })}><Plus /> Add voice</Button>}>
        {voices.length === 0 ? (
          <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">
            No voices yet. Add a short recording of the voice you want your VTuber to have.
          </div>
        ) : (
          <div className="divide-y rounded-xl border">
            {voices.map((voice) => (
              <VoiceRow key={voice.name} voice={voice} selected={voice.name === currentVoice} minRef={minRef}
                engineLabel={active?.label} onSelect={() => selectVoice(voice.name)}
                onEdit={() => setVoiceDialog({ mode: "edit", voice })} onDelete={() => deleteVoice(voice)} />
            ))}
          </div>
        )}
        {provider === "local" && <SpeedControl engineId={data?.active_engine} initial={data?.options.speed ?? 1} />}
      </Section>

      <VoiceDialog state={voiceDialog} onClose={() => setVoiceDialog(null)} onSaved={loadVoices} minRef={minRef} engineLabel={active?.label} />
      <LogDialog engine={data?.engines.find((e) => e.id === logFor) ?? null} onClose={() => setLogFor(null)} />
      {dialog}
    </PageBody>
  )
}

function SpeedControl({ engineId, initial }: { engineId?: string; initial: number }) {
  const [speed, setSpeed] = useState(initial)
  useEffect(() => setSpeed(initial), [initial])
  const supported = engineId ? SPEED_ENGINES.has(engineId) : false
  const save = (v: number) => api("/api/tts/options", { method: "POST", json: { speed: v } }).catch((e) => toast.error(e.message))
  return (
    <div className="mt-5 grid grid-cols-[auto_1fr_auto] items-center gap-4">
      <Label className="text-sm font-medium">Speaking speed</Label>
      <Slider min={0.5} max={2} step={0.05} value={[speed]} disabled={!supported}
        onValueChange={(v) => setSpeed(v[0])} onValueCommit={(v) => save(v[0])} />
      <span className="w-12 text-right text-sm tabular">{speed.toFixed(2)}×</span>
      {!supported && <p className="col-span-3 -mt-2 text-xs text-muted-foreground">The selected engine sets its own pace from the reference voice.</p>}
    </div>
  )
}

function VoiceRow({ voice, selected, minRef, engineLabel, onSelect, onEdit, onDelete }: {
  voice: Voice; selected: boolean; minRef: number; engineLabel?: string
  onSelect: () => void; onEdit: () => void; onDelete: () => void
}) {
  const [playing, setPlaying] = useState(false)
  const audio = useRef<HTMLAudioElement | null>(null)
  const tooShort = voice.duration != null && minRef > 0 && voice.duration < minRef

  const toggle = () => {
    if (playing) { audio.current?.pause(); setPlaying(false); return }
    audio.current = new Audio(`/api/tts/voices/${encodeURIComponent(voice.name)}/audio?t=${Date.now()}`)
    audio.current.onended = () => setPlaying(false)
    audio.current.play().then(() => setPlaying(true)).catch(() => setPlaying(false))
  }
  useEffect(() => () => audio.current?.pause(), [])

  return (
    <div className={cn("flex items-center gap-3 px-4 py-3", selected && "bg-primary/5")}>
      <input type="radio" name="voice" aria-label={`Use ${voice.name}`} checked={selected} onChange={onSelect}
        className="size-4 accent-[var(--primary)]" />
      <Button variant="outline" size="icon" className="rounded-full" onClick={toggle} aria-label={playing ? "Stop preview" : `Play ${voice.name} sample`}>
        {playing ? <Pause /> : <Play />}
      </Button>
      <button className="min-w-0 flex-1 text-left" onClick={onSelect}>
        <div className="flex items-center gap-2">
          <span className="font-medium">{voice.name}</span>
          <Badge variant="outline" className="text-[11px]">{LANGUAGES[voice.language] ?? voice.language}</Badge>
          {voice.duration != null && <span className="text-xs text-muted-foreground tabular">{voice.duration.toFixed(1)} s</span>}
          {tooShort && (
            <span className="inline-flex items-center gap-1 text-xs text-warning">
              <TriangleAlert className="size-3" /> Too short for {engineLabel} (needs {minRef}+ s)
            </span>
          )}
        </div>
        <p className="truncate text-xs text-muted-foreground">{voice.reference_text || "No transcript"}</p>
      </button>
      <Button variant="ghost" size="icon" onClick={onEdit} aria-label={`Edit ${voice.name}`}><Pencil /></Button>
      <Button variant="ghost" size="icon" onClick={onDelete} aria-label={`Delete ${voice.name}`} className="hover:text-destructive"><Trash2 /></Button>
    </div>
  )
}

function VoiceDialog({ state, onClose, onSaved, minRef, engineLabel }: {
  state: { mode: "add" } | { mode: "edit"; voice: Voice } | null
  onClose: () => void; onSaved: () => void; minRef: number; engineLabel?: string
}) {
  const editing = state?.mode === "edit" ? state.voice : null
  const [name, setName] = useState("")
  const [text, setText] = useState("")
  const [language, setLanguage] = useState("en")
  const [file, setFile] = useState<File | null>(null)
  const [fileDuration, setFileDuration] = useState<number | null>(null)
  const [dragging, setDragging] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!state) return
    setName(editing?.name ?? ""); setText(editing?.reference_text ?? ""); setLanguage(editing?.language ?? "en")
    setFile(null); setFileDuration(null); setError(null)
  }, [state]) // eslint-disable-line react-hooks/exhaustive-deps

  const pick = (f: File | undefined) => {
    if (!f) return
    if (!/^audio\//.test(f.type) && !/\.(wav|mp3|flac|ogg|m4a|opus|webm)$/i.test(f.name)) {
      setError("That is not an audio file. Use WAV, MP3, FLAC or OGG.")
      return
    }
    setError(null)
    setFile(f)
    if (!name) setName(f.name.replace(/\.[^.]+$/, "").replace(/[^\w\- .]/g, "_").slice(0, 60))
    const url = URL.createObjectURL(f)
    const a = new Audio(url)
    a.onloadedmetadata = () => { setFileDuration(a.duration); URL.revokeObjectURL(url) }
    a.onerror = () => URL.revokeObjectURL(url)
  }

  const save = async () => {
    setSaving(true); setError(null)
    const form = new FormData()
    form.append("name", name.trim())
    form.append("reference_text", text)
    form.append("reference_language", language)
    form.append("replace", editing ? "true" : "false")
    if (file) form.append("reference_audio", file)
    try {
      const res = await fetch("/api/tts/upload", { method: "POST", body: form })
      if (!res.ok) throw new Error(await readError(res))
      toast.success(editing ? `Updated ${name}` : `Added ${name}`)
      onSaved()
      onClose()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const duration = fileDuration ?? (editing && !file ? editing.duration : null)
  const short = duration != null && minRef > 0 && duration < minRef

  return (
    <Dialog open={!!state} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? `Edit “${editing.name}”` : "Add a voice"}</DialogTitle>
          <DialogDescription>Upload a clean recording of one speaker. Typing exactly what is said improves the clone.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div
            className={cn("flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed p-6 text-center transition-colors",
              dragging ? "border-primary bg-primary/10" : "hover:border-primary/50 hover:bg-accent/40")}
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files[0]) }}
            role="button" tabIndex={0} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
          >
            {file ? <FileAudio className="size-6 text-primary" /> : <Upload className="size-6 text-muted-foreground" />}
            <div className="text-sm font-medium">
              {file ? file.name : editing ? "Drop a new recording to replace the current one (optional)" : "Drop an audio file here or click to browse"}
            </div>
            <div className="text-xs text-muted-foreground">
              {duration != null ? `${duration.toFixed(1)} seconds` : "WAV, MP3, FLAC or OGG · 6–15 seconds is ideal"}
            </div>
            <input ref={inputRef} type="file" accept="audio/*,.wav,.mp3,.flac,.ogg,.m4a" className="hidden" onChange={(e) => pick(e.target.files?.[0])} />
          </div>
          {short && (
            <p className="flex items-center gap-1.5 text-xs text-warning">
              <TriangleAlert className="size-3.5" /> {engineLabel} needs at least {minRef} seconds. Other engines can still use it.
            </p>
          )}
          <div className="grid grid-cols-[1fr_10rem] gap-3">
            <div className="space-y-2">
              <Label htmlFor="voice-name">Name</Label>
              <Input id="voice-name" value={name} disabled={!!editing} maxLength={60} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>Language</Label>
              <Select value={language} onValueChange={setLanguage}>
                <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {Object.entries(LANGUAGES).map(([k, v]) => <SelectItem key={k} value={k}>{v}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="voice-text">What is said in the recording</Label>
            <Textarea id="voice-text" rows={3} value={text} onChange={(e) => setText(e.target.value)}
              placeholder="Type the exact words spoken in the clip. Required for GPT-SoVITS and TADA; optional for the others." />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={save} disabled={saving || !name.trim() || (!editing && !file)}>
            {saving ? <Loader2 className="animate-spin" /> : <Check />} {editing ? "Save changes" : "Add voice"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function VoiceTester({ engineLabel, voice }: { engineLabel?: string; voice: string | null }) {
  const [text, setText] = useState("Hey chat! Thanks for hanging out with me today.")
  const [state, setState] = useState<"idle" | "working" | "playing">("idle")
  const [result, setResult] = useState<{ url: string; ms: number } | null>(null)
  const audio = useRef<HTMLAudioElement | null>(null)

  const speak = async () => {
    if (!text.trim()) return
    audio.current?.pause()
    setState("working")
    const t0 = performance.now()
    try {
      const url = await ttsManager.generateAudioFromText(text)
      const ms = performance.now() - t0
      if (result) URL.revokeObjectURL(result.url)
      setResult({ url, ms })
      audio.current = new Audio(url)
      audio.current.onended = () => setState("idle")
      await audio.current.play()
      setState("playing")
    } catch (e) {
      toast.error((e as Error).message)
      setState("idle")
    }
  }

  return (
    <div className="rounded-2xl border bg-card p-4 shadow-xs">
      <div className="flex items-center gap-3">
        <Volume2 className="size-5 shrink-0 text-primary" />
        <Input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && speak()}
          placeholder="Type something to hear it" aria-label="Text to speak" className="h-10" />
        {state === "playing" ? (
          <Button variant="outline" onClick={() => { audio.current?.pause(); setState("idle") }}><Square /> Stop</Button>
        ) : (
          <Button onClick={speak} disabled={state === "working" || !text.trim()} className="min-w-28">
            {state === "working" ? <><Loader2 className="animate-spin" /> Speaking…</> : <><Play /> Speak</>}
          </Button>
        )}
        {result && (
          <a href={result.url} download={`voice-${Date.now()}.wav`} aria-label="Download last clip">
            <Button variant="ghost" size="icon"><Download /></Button>
          </a>
        )}
      </div>
      <p className="mt-2 pl-8 text-xs text-muted-foreground tabular">
        {engineLabel ?? "No engine"} · voice “{voice ?? "none"}”
        {result && <> · generated in <span className="text-foreground">{(result.ms / 1000).toFixed(2)} s</span></>}
      </p>
    </div>
  )
}

function LogDialog({ engine, onClose }: { engine: Engine | null; onClose: () => void }) {
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => endRef.current?.scrollIntoView(), [engine?.log.length])
  return (
    <Dialog open={!!engine} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{engine?.label} log</DialogTitle>
          <DialogDescription>Recent output from installing and running this engine (kept in memory only).</DialogDescription>
        </DialogHeader>
        <div className="max-h-[60vh] overflow-auto rounded-lg bg-muted p-3 font-mono text-[11px] leading-relaxed">
          {engine?.log.length ? engine.log.map((l, i) => <div key={i} className="whitespace-pre-wrap break-all">{l}</div>) : "No output yet."}
          <div ref={endRef} />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => navigator.clipboard.writeText(engine?.log.join("\n") ?? "").then(() => toast.success("Copied"))}>Copy</Button>
          <Button onClick={onClose}>Close</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
