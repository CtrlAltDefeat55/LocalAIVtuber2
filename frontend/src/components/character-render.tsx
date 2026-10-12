import { useCallback, useEffect, useRef, useState } from "react"
import { Box, Eye, EyeOff, FolderOpen, FolderUp, Loader2, MoreHorizontal, PanelRightClose, PanelRightOpen, RefreshCw, RotateCcw, Trash2, Upload, UserRound } from "lucide-react"
import { toast } from "sonner"
import Live2DCanvas from "@/components/live-2d-renderer"
import VRM3dCanvas from "@/components/vrm-3d-renderer"
import SettingSlider from "@/components/setting-slider"
import { Button } from "@/components/ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { useConfirm } from "@/components/confirm-dialog"
import { useSettings } from "@/context/SettingsContext"
import { fetchLive2DModels, fetchVRMModels, CharacterModel } from "@/lib/characterModels"
import { api, readError } from "@/lib/api"
import { cn } from "@/lib/utils"

const IDS = {
  is2D: "frontend.character.3d2dSwitch", // true = Live2D (2D), false = VRM (3D)
  show: "frontend.character.renderModel",
  live2d: "frontend.character.selectedLive2DModel",
  vrm: "frontend.character.selectedVRMModel",
  x: "frontend.character.live2D.xPosition",
  y: "frontend.character.live2D.yPosition",
  scale: "frontend.character.live2D.scale",
}
const DEFAULTS = { x: 50, y: 100, scale: 0.3 }
const PANEL_KEY = "lav.character.panel"

type Kind = "live2d" | "vrm"

export function CharacterRender() {
  const { settings, updateSetting } = useSettings()
  const [live2DModels, setLive2DModels] = useState<CharacterModel[]>([])
  const [vrmModels, setVrmModels] = useState<CharacterModel[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const [panelOpen, setPanelOpen] = useState(() => {
    try { return localStorage.getItem(PANEL_KEY) !== "closed" } catch { return true }
  })
  const { confirm, dialog } = useConfirm()
  const zipInput = useRef<HTMLInputElement>(null)
  const folderInput = useRef<HTMLInputElement>(null)
  const vrmInput = useRef<HTMLInputElement>(null)
  const replaceTarget = useRef<CharacterModel | null>(null)

  const is2D = settings[IDS.is2D] === true
  const kind: Kind = is2D ? "live2d" : "vrm"
  const show = settings[IDS.show] !== false
  const models = kind === "live2d" ? live2DModels : vrmModels
  const selectedPath = settings[kind === "live2d" ? IDS.live2d : IDS.vrm]
  const selectedExists = models.some((m) => m.path === selectedPath)

  const loadModels = useCallback(async () => {
    setLoading(true)
    try {
      const [l2d, vrm] = await Promise.all([fetchLive2DModels(), fetchVRMModels()])
      setLive2DModels(l2d)
      setVrmModels(vrm)
      return { l2d, vrm }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadModels() }, [loadModels])

  // Pick a default model once the list is known (or when the saved one was deleted).
  useEffect(() => {
    if (loading) return
    if (live2DModels.length && !live2DModels.some((m) => m.path === settings[IDS.live2d])) updateSetting(IDS.live2d, live2DModels[0].path)
    if (vrmModels.length && !vrmModels.some((m) => m.path === settings[IDS.vrm])) updateSetting(IDS.vrm, vrmModels[0].path)
  }, [loading, live2DModels, vrmModels]) // eslint-disable-line react-hooks/exhaustive-deps

  const togglePanel = () => {
    setPanelOpen((open) => {
      try { localStorage.setItem(PANEL_KEY, open ? "closed" : "open") } catch { /* ignore */ }
      return !open
    })
  }

  const upload = async (target: Kind, files: File[], opts: { replace?: CharacterModel | null; folder?: boolean } = {}) => {
    const form = new FormData()
    let url: string
    if (target === "vrm") {
      form.append("file", files[0])
      url = "/api/character/vrm/upload"
    } else if (opts.folder) {
      files.forEach((f) => form.append("files", f, f.webkitRelativePath || f.name))
      url = "/api/character/live2d/upload-folder"
    } else {
      form.append("file", files[0])
      url = "/api/character/live2d/upload-zip"
    }
    if (opts.replace) {
      form.append("replace", "true")
      form.append("target_name", opts.replace.name)
    }
    setUploading(opts.replace ? `Updating ${opts.replace.displayName}…` : "Installing model…")
    try {
      const res = await fetch(url, { method: "POST", body: form })
      if (!res.ok) throw new Error(await readError(res))
      const before = new Set((target === "vrm" ? vrmModels : live2DModels).map((m) => m.path))
      const { l2d, vrm } = await loadModels()
      const list = target === "vrm" ? vrm : l2d
      const added = list.find((m) => !before.has(m.path))
      if (added) {
        await updateSetting(target === "vrm" ? IDS.vrm : IDS.live2d, added.path)
        await updateSetting(IDS.is2D, target === "live2d")
      }
      toast.success(opts.replace ? `${opts.replace.displayName} updated` : `${added?.displayName ?? "Model"} added`)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setUploading(null)
    }
  }

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (!file) return
    if (/\.vrm$/i.test(file.name)) upload("vrm", [file])
    else if (/\.zip$/i.test(file.name)) upload("live2d", [file])
    else toast.error("Drop a .vrm file (3D) or a .zip of a Live2D model folder (2D).")
  }

  const remove = async (model: CharacterModel) => {
    const ok = await confirm({
      title: `Delete ${model.displayName}?`,
      description: kind === "live2d" ? "The whole model folder is removed from the app." : "The .vrm file is removed from the app.",
      confirmLabel: "Delete model",
    })
    if (!ok) return
    try {
      await api(`/api/character/${kind === "live2d" ? "live2d" : "vrm"}/delete`, { method: "POST", json: { path: model.path } })
      toast.success(`${model.displayName} deleted`)
      await loadModels()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  const x = settings[IDS.x] ?? DEFAULTS.x
  const y = settings[IDS.y] ?? DEFAULTS.y
  const scale = settings[IDS.scale] ?? DEFAULTS.scale

  return (
    <div className="flex h-full w-full overflow-hidden">
      {/* Stage */}
      <div
        className={cn("relative min-w-0 flex-1 bg-[radial-gradient(ellipse_at_bottom,var(--accent),transparent_70%)]",
          dragging && "outline-2 -outline-offset-8 outline-dashed outline-primary")}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        {show && selectedPath && selectedExists ? (
          kind === "live2d"
            ? <Live2DCanvas modelPath={selectedPath} xPosition={Number(x)} yPosition={Number(y)} scale={Number(scale)} />
            : <VRM3dCanvas modelPath={selectedPath} key={selectedPath} />
        ) : (
          <div className="grid h-full place-items-center p-8 text-center">
            <div className="max-w-sm space-y-2 text-sm text-muted-foreground">
              <UserRound className="mx-auto size-10 opacity-50" />
              <p className="text-base font-medium text-foreground">
                {loading ? "Loading models…" : !show ? "Character hidden" : models.length === 0 ? `No ${kind === "live2d" ? "Live2D" : "VRM"} models yet` : "Pick a model"}
              </p>
              <p>{!show ? "Turn on “Show character” in the panel." : "Drop a .zip (Live2D) or .vrm (3D) file here, or use the panel on the right."}</p>
            </div>
          </div>
        )}
        {uploading && (
          <div className="absolute inset-x-0 top-4 mx-auto flex w-fit items-center gap-2 rounded-full border bg-popover px-4 py-2 text-sm shadow-md">
            <Loader2 className="size-4 animate-spin" /> {uploading}
          </div>
        )}
        <Button variant="outline" size="sm" className="absolute right-3 top-3 bg-background/80 backdrop-blur" onClick={togglePanel}
          aria-label={panelOpen ? "Hide panel" : "Show panel"}>
          {panelOpen ? <PanelRightClose /> : <PanelRightOpen />} {panelOpen ? "Hide panel" : "Customize"}
        </Button>
      </div>

      {/* Inspector */}
      {panelOpen && (
        <aside className="w-[340px] shrink-0 overflow-y-auto border-l bg-sidebar">
          <div className="space-y-6 p-5">
            <div>
              <h1 className="text-lg font-semibold">Character</h1>
              <p className="text-[13px] text-muted-foreground">Your VTuber's body. Lip sync follows the voice automatically.</p>
            </div>

            <div className="space-y-2">
              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Renderer</div>
              <div className="grid grid-cols-2 gap-1 rounded-xl bg-muted p-1" role="radiogroup" aria-label="Renderer">
                {([["live2d", "2D · Live2D", UserRound], ["vrm", "3D · VRM", Box]] as const).map(([k, label, Icon]) => (
                  <button key={k} role="radio" aria-checked={kind === k}
                    onClick={() => updateSetting(IDS.is2D, k === "live2d", { immediate: true })}
                    className={cn("flex items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-sm transition-colors",
                      kind === k ? "bg-background font-medium shadow-sm" : "text-muted-foreground hover:text-foreground")}>
                    <Icon className="size-4" /> {label}
                  </button>
                ))}
              </div>
              <Button variant="ghost" size="sm" className="w-full justify-start" onClick={() => updateSetting(IDS.show, !show, { immediate: true })}>
                {show ? <EyeOff /> : <Eye />} {show ? "Hide character (saves GPU)" : "Show character"}
              </Button>
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{kind === "live2d" ? "Live2D models" : "VRM models"}</div>
                <div className="flex">
                  <Button variant="ghost" size="icon" className="size-7" aria-label="Rescan models" title="Rescan" onClick={loadModels}><RefreshCw className="size-3.5" /></Button>
                  <Button variant="ghost" size="icon" className="size-7" aria-label="Open models folder" title="Open folder"
                    onClick={() => api("/api/system/open-folder", { method: "POST", json: { which: kind } }).catch((e) => toast.error(e.message))}>
                    <FolderOpen className="size-3.5" />
                  </Button>
                </div>
              </div>
              <div className="overflow-hidden rounded-xl border bg-background">
                {models.length === 0 && <div className="p-4 text-center text-xs text-muted-foreground">{loading ? "Loading…" : "None installed yet."}</div>}
                {models.map((m) => (
                  <div key={m.path} className={cn("flex items-center gap-2 border-b px-3 py-2 last:border-b-0", m.path === selectedPath && "bg-primary/10")}>
                    <button className="min-w-0 flex-1 truncate text-left text-sm" onClick={() => updateSetting(kind === "live2d" ? IDS.live2d : IDS.vrm, m.path, { immediate: true })}>
                      <span className={cn(m.path === selectedPath && "font-medium text-primary")}>{m.displayName}</span>
                      {m.missing && m.missing.length > 0 && (
                        <span className="block text-[11px] text-warning" title={m.missing.join("\n")}>
                          Missing {m.missing.length} file{m.missing.length > 1 ? "s" : ""} (textures) — use Replace
                        </span>
                      )}
                    </button>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" className="size-7" aria-label={`Actions for ${m.displayName}`}><MoreHorizontal /></Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => { replaceTarget.current = m; (kind === "live2d" ? zipInput : vrmInput).current?.click() }}>
                          <Upload /> Replace with new file…
                        </DropdownMenuItem>
                        {kind === "live2d" && (
                          <DropdownMenuItem onClick={() => { replaceTarget.current = m; folderInput.current?.click() }}>
                            <FolderUp /> Replace with folder…
                          </DropdownMenuItem>
                        )}
                        <DropdownMenuSeparator />
                        <DropdownMenuItem variant="destructive" onClick={() => remove(m)}><Trash2 /> Delete</DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                ))}
              </div>
              {kind === "live2d" ? (
                <div className="grid grid-cols-2 gap-2">
                  <Button variant="outline" size="sm" onClick={() => { replaceTarget.current = null; zipInput.current?.click() }}><Upload /> Add .zip</Button>
                  <Button variant="outline" size="sm" onClick={() => { replaceTarget.current = null; folderInput.current?.click() }}><FolderUp /> Add folder</Button>
                </div>
              ) : (
                <Button variant="outline" size="sm" className="w-full" onClick={() => { replaceTarget.current = null; vrmInput.current?.click() }}><Upload /> Add .vrm</Button>
              )}
              <p className="text-xs text-muted-foreground">
                {kind === "live2d" ? "Cubism 3/4 models (folder with a .model3.json). VTube Studio exports work." : "VRM 0.x / 1.0 files, e.g. from VRoid Studio."}
              </p>
            </div>

            {kind === "live2d" && (
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Position & size</div>
                  <Button variant="ghost" size="sm" className="h-7" onClick={() => {
                    updateSetting(IDS.x, DEFAULTS.x); updateSetting(IDS.y, DEFAULTS.y); updateSetting(IDS.scale, DEFAULTS.scale)
                  }}><RotateCcw /> Reset</Button>
                </div>
                <SettingSlider id={IDS.x} label="Horizontal" unit="%" min={-50} max={150} step={1} defaultValue={DEFAULTS.x}
                  description="Model centre across the stage: 0% left edge, 50% centre, 100% right edge." />
                <SettingSlider id={IDS.y} label="Vertical" unit="%" min={-50} max={250} step={1} defaultValue={DEFAULTS.y}
                  description="Model centre down the stage: 0% top, 100% bottom. Above 100% crops the legs." />
                <SettingSlider id={IDS.scale} label="Size" unit="×" min={0.02} max={3} step={0.01} defaultValue={DEFAULTS.scale}
                  description="Multiplier of the model's native size." />
              </div>
            )}
            {kind === "vrm" && (
              <p className="rounded-lg bg-muted p-3 text-xs text-muted-foreground">Drag on the stage to orbit the camera, scroll to zoom.</p>
            )}
          </div>
        </aside>
      )}

      <input ref={zipInput} type="file" accept=".zip" className="hidden"
        onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) upload("live2d", [f], { replace: replaceTarget.current }) }} />
      <input ref={folderInput} type="file" className="hidden" multiple
        {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
        onChange={(e) => { const fs = Array.from(e.target.files ?? []); e.target.value = ""; if (fs.length) upload("live2d", fs, { folder: true, replace: replaceTarget.current }) }} />
      <input ref={vrmInput} type="file" accept=".vrm" className="hidden"
        onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) upload("vrm", [f], { replace: replaceTarget.current }) }} />
      {dialog}
    </div>
  )
}
