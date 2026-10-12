import { useEffect, useRef, useState } from "react"
import { Check, KeyRound, Loader2, Play, PlugZap, TriangleAlert } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { useSystemStatus } from "@/context/SystemStatusContext"
import { api, readError } from "@/lib/api"

interface Provider { label: string; base_url: string; needs_key: boolean; has_model: boolean; default_model?: string; help: string }
interface RemoteInfo {
  providers: Record<string, Provider>
  source: string
  remote: { base_url: string; voice: string; voice_name: string; model: string; language: string }
  has_key: Record<string, boolean>
  key_storage: string
}
interface RemoteVoice { id: string; name: string; language?: string }

/** Voicebox (this or another PC), any OpenAI-compatible speech API, or ElevenLabs. */
export function RemoteVoicePanel({ providers: allowed, onSaved }: { providers: string[]; onSaved: () => void }) {
  const { refresh } = useSystemStatus()
  const [info, setInfo] = useState<RemoteInfo | null>(null)
  const [provider, setProvider] = useState(allowed[0])
  const [baseUrl, setBaseUrl] = useState("")
  const [key, setKey] = useState("")
  const [model, setModel] = useState("")
  const [voices, setVoices] = useState<RemoteVoice[] | null>(null)
  const [voice, setVoice] = useState("")
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const audio = useRef<HTMLAudioElement | null>(null)

  useEffect(() => {
    api<RemoteInfo>("/api/tts/remote").then((d) => {
      setInfo(d)
      const current = allowed.includes(d.source) ? d.source : allowed[0]
      setProvider(current)
      const p = d.providers[current]
      setBaseUrl(d.source === current && d.remote.base_url ? d.remote.base_url : p.base_url)
      setModel(d.source === current && d.remote.model ? d.remote.model : p.default_model ?? "")
      if (d.source === current && d.remote.voice) {
        setVoice(d.remote.voice)
        setVoices([{ id: d.remote.voice, name: d.remote.voice_name || d.remote.voice }])
      }
    }).catch((e) => setError(e.message))
  }, [allowed.join()]) // eslint-disable-line react-hooks/exhaustive-deps

  const p = info?.providers[provider]

  const choose = (value: string) => {
    setProvider(value)
    setBaseUrl(info?.providers[value].base_url ?? "")
    setModel(info?.providers[value].default_model ?? "")
    setVoices(null); setVoice(""); setError(null)
  }

  const test = async () => {
    setTesting(true); setError(null)
    try {
      const r = await api<{ base_url: string; voices: RemoteVoice[] }>("/api/tts/remote/test", {
        method: "POST", json: { provider, base_url: baseUrl, api_key: key || null },
      })
      setBaseUrl(r.base_url)
      setVoices(r.voices)
      if (!r.voices.some((v) => v.id === voice)) setVoice(r.voices[0]?.id ?? "")
      if (r.voices.length === 0) setError(provider === "voicebox" ? "Connected, but Voicebox has no voice profiles yet. Create one in Voicebox first." : "Connected, but no voices were listed.")
      else toast.success(`Connected: ${r.voices.length} voice${r.voices.length === 1 ? "" : "s"}`)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setTesting(false)
    }
  }

  const selected = voices?.find((v) => v.id === voice)

  const save = async () => {
    setSaving(true); setError(null)
    try {
      await api("/api/tts/remote", {
        method: "POST",
        json: { provider, base_url: baseUrl, voice, voice_name: selected?.name ?? voice, model, language: selected?.language ?? "en",
          api_key: key ? key : null, use: true },
      })
      setKey("")
      toast.success(`Voice: ${selected?.name ?? voice} via ${p?.label}. Local voice engines were stopped to free memory.`)
      refresh()
      onSaved()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const preview = async () => {
    setPreviewing(true)
    try {
      await save()
      const res = await fetch("/api/tts", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: "Hi! This is how I sound." }) })
      if (!res.ok) throw new Error(await readError(res))
      audio.current?.pause()
      audio.current = new Audio(URL.createObjectURL(await res.blob()))
      await audio.current.play()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setPreviewing(false)
    }
  }

  if (!info) return <div className="text-sm text-muted-foreground">{error ?? "Loading…"}</div>

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-[14rem_1fr]">
        <div className="space-y-2">
          <Label>Service</Label>
          <Select value={provider} onValueChange={choose} disabled={allowed.length === 1}>
            <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent>
              {allowed.map((k) => <SelectItem key={k} value={k}>{info.providers[k].label}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="tts-url">Address</Label>
          <Input id="tts-url" value={baseUrl} onChange={(e) => { setBaseUrl(e.target.value); setVoices(null) }}
            onKeyDown={(e) => e.key === "Enter" && test()} />
        </div>
      </div>
      {p?.help && <p className="-mt-2 text-xs text-muted-foreground">{p.help}</p>}

      {provider !== "voicebox" && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="tts-key" className="flex items-center gap-1.5"><KeyRound className="size-3.5" /> API key</Label>
            <Input id="tts-key" type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)}
              placeholder={info.has_key[provider] ? "A key is saved. Type a new one to replace it." : p?.needs_key ? "Paste your key" : "Only if the server needs one"} />
          </div>
          {p?.has_model && (
            <div className="space-y-2">
              <Label htmlFor="tts-model">Model</Label>
              <Input id="tts-model" value={model} onChange={(e) => setModel(e.target.value)} placeholder={p.default_model} />
            </div>
          )}
        </div>
      )}
      {provider !== "voicebox" && <p className="-mt-2 text-xs text-muted-foreground">Keys are kept in {info.key_storage}.</p>}

      <div className="flex flex-wrap items-end gap-3">
        <Button variant="outline" onClick={test} disabled={!baseUrl.trim() || testing}>
          {testing ? <Loader2 className="animate-spin" /> : <PlugZap />} Test connection
        </Button>
        <div className="min-w-56 flex-1 space-y-2">
          <Label>Voice</Label>
          {voices && voices.length > 0 ? (
            <Select value={voice} onValueChange={setVoice}>
              <SelectTrigger className="w-full"><SelectValue placeholder="Pick a voice" /></SelectTrigger>
              <SelectContent>{voices.map((v) => <SelectItem key={v.id} value={v.id}>{v.name}{v.language ? ` (${v.language})` : ""}</SelectItem>)}</SelectContent>
            </Select>
          ) : (
            <Input value={voice} onChange={(e) => setVoice(e.target.value)} placeholder="Test the connection to list voices" />
          )}
        </div>
        <Button variant="outline" onClick={preview} disabled={!voice || previewing || saving}>
          {previewing ? <Loader2 className="animate-spin" /> : <Play />} Preview
        </Button>
        <Button onClick={save} disabled={!baseUrl.trim() || !voice || saving}>
          {saving ? <Loader2 className="animate-spin" /> : <Check />} Use this voice
        </Button>
      </div>

      {error && (
        <div className="flex gap-2 rounded-xl border border-destructive/40 bg-destructive/10 p-3 text-[13px]">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-destructive" /> <span>{error}</span>
        </div>
      )}
    </div>
  )
}
