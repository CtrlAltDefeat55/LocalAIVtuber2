import { useEffect, useState } from "react"
import { Check, KeyRound, Loader2, PlugZap, TriangleAlert } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { useSystemStatus } from "@/context/SystemStatusContext"
import { api } from "@/lib/api"

interface Preset { label: string; base_url: string; needs_key: boolean; local_server: boolean; help: string }
interface RemoteInfo {
  presets: Record<string, Preset>
  provider: "local" | "remote"
  remote: { preset: string; base_url: string; model: string }
  has_key: boolean
  key_storage: string
}

/** Connect the brain to LM Studio / Ollama on any PC, or a paid OpenAI-compatible API. */
export function RemoteLLMPanel() {
  const { status, refresh } = useSystemStatus()
  const [info, setInfo] = useState<RemoteInfo | null>(null)
  const [preset, setPreset] = useState("lmstudio")
  const [baseUrl, setBaseUrl] = useState("")
  const [key, setKey] = useState("")
  const [models, setModels] = useState<string[] | null>(null)
  const [model, setModel] = useState("")
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api<RemoteInfo>("/api/llm/remote").then((d) => {
      setInfo(d)
      const p = d.remote.preset || "lmstudio"
      setPreset(p)
      setBaseUrl(d.remote.base_url || d.presets[p]?.base_url || "")
      setModel(d.remote.model || "")
    }).catch((e) => setError(e.message))
  }, [])

  const p = info?.presets[preset]
  const usingRemote = status?.llm.provider === "remote"

  const choosePreset = (value: string) => {
    setPreset(value)
    setBaseUrl(info?.presets[value]?.base_url ?? "")
    setModels(null)
    setError(null)
  }

  const test = async () => {
    setTesting(true); setError(null); setModels(null)
    try {
      const r = await api<{ base_url: string; models: string[] }>("/api/llm/remote/test", {
        method: "POST", json: { preset, base_url: baseUrl, api_key: key || null },
      })
      setBaseUrl(r.base_url)
      setModels(r.models)
      if (!r.models.includes(model)) setModel(r.models[0] ?? "")
      toast.success(`Connected: ${r.models.length} model${r.models.length === 1 ? "" : "s"} available`)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setTesting(false)
    }
  }

  const save = async (use: boolean) => {
    setSaving(true); setError(null)
    try {
      await api("/api/llm/remote", { method: "POST", json: { preset, base_url: baseUrl, model, api_key: key ? key : null, use } })
      setKey("")
      toast.success(use ? `Using ${model} through ${p?.label}. The local model was unloaded.` : "Saved")
      refresh()
      setInfo(await api<RemoteInfo>("/api/llm/remote"))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  if (!info) return <div className="text-sm text-muted-foreground">{error ?? "Loading…"}</div>

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-[14rem_1fr]">
        <div className="space-y-2">
          <Label>Service</Label>
          <Select value={preset} onValueChange={choosePreset}>
            <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent>
              {Object.entries(info.presets).map(([k, v]) => <SelectItem key={k} value={k}>{v.label}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="llm-url">Address</Label>
          <Input id="llm-url" value={baseUrl} onChange={(e) => { setBaseUrl(e.target.value); setModels(null) }}
            placeholder="http://192.168.1.20:1234/v1" onKeyDown={(e) => e.key === "Enter" && test()} />
        </div>
      </div>
      {p?.help && <p className="-mt-2 text-xs text-muted-foreground">{p.help}</p>}

      <div className="space-y-2">
        <Label htmlFor="llm-key" className="flex items-center gap-1.5">
          <KeyRound className="size-3.5" /> API key {p?.needs_key ? "" : <span className="font-normal text-muted-foreground">(not needed for {p?.label})</span>}
        </Label>
        <Input id="llm-key" type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)}
          placeholder={info.has_key ? "A key is saved. Type a new one to replace it." : p?.needs_key ? "Paste your key" : "Optional"} />
        <p className="text-xs text-muted-foreground">Keys are kept in {info.key_storage}, never in the app's settings file.</p>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <Button variant="outline" onClick={test} disabled={!baseUrl.trim() || testing}>
          {testing ? <Loader2 className="animate-spin" /> : <PlugZap />} Test connection
        </Button>
        <div className="min-w-56 flex-1 space-y-2">
          <Label>Model</Label>
          {models && models.length > 0 ? (
            <Select value={model} onValueChange={setModel}>
              <SelectTrigger className="w-full"><SelectValue placeholder="Pick a model" /></SelectTrigger>
              <SelectContent>{models.map((m) => <SelectItem key={m} value={m}>{m}</SelectItem>)}</SelectContent>
            </Select>
          ) : (
            <Input value={model} onChange={(e) => setModel(e.target.value)} placeholder="Test the connection to list models, or type a name" />
          )}
        </div>
        <Button onClick={() => save(true)} disabled={!baseUrl.trim() || !model.trim() || saving}>
          {saving ? <Loader2 className="animate-spin" /> : <Check />} Use this API
        </Button>
      </div>

      {error && (
        <div className="flex gap-2 rounded-xl border border-destructive/40 bg-destructive/10 p-3 text-[13px]">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-destructive" /> <span>{error}</span>
        </div>
      )}
      {usingRemote && status?.llm.error && status.llm.state === "error" && (
        <div className="flex gap-2 rounded-xl border border-destructive/40 bg-destructive/10 p-3 text-[13px]">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-destructive" /> <span>Last request failed: {status.llm.error}</span>
        </div>
      )}
    </div>
  )
}
