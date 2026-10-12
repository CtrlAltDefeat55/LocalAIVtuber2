import Chatbox from "@/components/chatbox"
import { LLMMonitor } from "@/components/llm-monitor"
import { StatusDot } from "@/components/layout"
import { Button } from "@/components/ui/button"
import { useSettings } from "@/context/SettingsContext"
import { useSystemStatus } from "@/context/SystemStatusContext"
import { goToPage } from "@/lib/api"
import { cn } from "@/lib/utils"
import { ArrowRight, AudioLines, Brain, Check, PanelRight } from "lucide-react"

export type SessionInfo = {
    title: string,
    id: string
}

function SetupChecklist() {
    const { status } = useSystemStatus()
    if (!status) return null
    const steps = [
        {
            done: status.llm.model_downloaded,
            title: "Get a brain",
            text: status.llm.provider === "remote" ? "Finish connecting your API on the Brain page."
                : `Download ${status.llm.model_name ?? "a language model"}, or connect LM Studio / an API.`,
            action: "Open Brain", page: "brain", icon: Brain,
        },
        {
            done: !["not_installed", "installing"].includes(status.tts.state),
            title: "Set up a voice",
            text: status.tts.state === "installing" ? "Installing… you can keep using the app."
                : status.tts.source !== "local" ? "Pick a voice from your connected voice service."
                : "Install an engine (one click) or connect Voicebox / an API.",
            action: "Open Voice", page: "tts", icon: AudioLines,
        },
    ]
    if (steps.every((s) => s.done)) return null
    return (
        <div className="border-b bg-accent/40 px-6 py-4">
            <div className="mx-auto max-w-3xl">
                <div className="mb-3 text-sm font-semibold">Finish setting up your VTuber</div>
                <div className="grid gap-2 sm:grid-cols-2">
                    {steps.map((s, i) => (
                        <div key={s.title} className={cn("flex items-center gap-3 rounded-xl border bg-card p-3", s.done && "opacity-60")}>
                            <div className={cn("grid size-8 shrink-0 place-items-center rounded-full text-sm font-semibold",
                                s.done ? "bg-success/20 text-success" : "bg-primary/15 text-primary")}>
                                {s.done ? <Check className="size-4" /> : i + 1}
                            </div>
                            <div className="min-w-0 flex-1">
                                <div className="text-sm font-medium">{s.title}</div>
                                <div className="truncate text-xs text-muted-foreground">{s.done ? "Done" : s.text}</div>
                            </div>
                            {!s.done && <Button size="sm" onClick={() => goToPage(s.page)}>{s.action} <ArrowRight /></Button>}
                        </div>
                    ))}
                </div>
            </div>
        </div>
    )
}

function StudioHeader({ monitorOpen, onToggleMonitor }: { monitorOpen: boolean; onToggleMonitor: () => void }) {
    const { status } = useSystemStatus()
    const llm = status?.llm
    const tts = status?.tts
    return (
        <div className="flex items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-1">
                <Button variant="ghost" size="sm" className="min-w-0" onClick={() => goToPage("brain")} title="Change model on the Brain page">
                    <Brain />
                    <span className="truncate">{llm?.model_name ?? "No model"}</span>
                    <StatusDot tone={llm?.state === "ready" ? "ok" : llm?.state === "loading" ? "busy" : llm?.state === "error" ? "error" : "off"} />
                </Button>
                <Button variant="ghost" size="sm" className="min-w-0" onClick={() => goToPage("tts")} title="Change voice on the Voice page">
                    <AudioLines />
                    <span className="truncate">{tts?.current_voice ?? "No voice"}</span>
                    <StatusDot tone={tts?.state === "ready" ? "ok" : ["starting", "installing"].includes(tts?.state ?? "") ? "busy" : tts?.state === "error" ? "error" : "off"} />
                </Button>
            </div>
            <Button variant={monitorOpen ? "secondary" : "ghost"} size="sm" onClick={onToggleMonitor} title="Show what the model receives (prompt, memory, screen context)">
                <PanelRight /> Context
            </Button>
        </div>
    )
}

function LLMPage() {
    const { settings, updateSetting } = useSettings()
    const monitorOpen = Boolean(settings["llm.showMonitor"])

    return (
        <div className="flex h-full w-full flex-col overflow-hidden">
            <SetupChecklist />
            <div className="flex min-h-0 flex-1">
                <div className="min-w-0 flex-1">
                    <Chatbox header={<StudioHeader monitorOpen={monitorOpen} onToggleMonitor={() => updateSetting("llm.showMonitor", !monitorOpen, { immediate: true })} />} />
                </div>
                {monitorOpen && (
                    <aside className="w-[420px] shrink-0 overflow-y-auto border-l bg-sidebar/50">
                        <LLMMonitor />
                    </aside>
                )}
            </div>
        </div>
    )
}

export default LLMPage
