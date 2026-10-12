import InputPage from "@/pages/inputPage"
import LLMPage from "@/pages/llmPage"
import BrainPage from "@/pages/brainPage"
import PipelineMonitorPage from "@/pages/pipelineMonitorPage"
import SettingsPage from "@/pages/settingsPage"
import TTSPage from "@/pages/ttsPage"
import CharacterPage from "@/pages/characterPage"
import StreamPage from "@/pages/streamPage"
import MemoryPage from "@/pages/memoryPage"
import VisionPage from "@/pages/visionPage"
import { AudioLines, Brain, Database, Mic, MonitorPlay, Radio, Settings, SquareActivity, Sparkles, UserRound } from "lucide-react"
import type { LucideIcon } from "lucide-react"

interface PageComponentProps {
  isActive: boolean;
}

type PageComponent = React.ComponentType<PageComponentProps>;

export interface PageConfig {
  page: PageComponent;
  icon: LucideIcon;
  title: string;
  /** Short purpose shown as the sidebar tooltip. */
  hint: string;
  /** Unmount when hidden (pages that hold nothing live). */
  unmountWhenHidden?: boolean;
}

const pageMapping = {
  "llm": { page: LLMPage, icon: Sparkles, title: "Studio", hint: "Talk with your VTuber" },
  "character": { page: CharacterPage, icon: UserRound, title: "Character", hint: "2D/3D model, position and uploads" },
  "stream": { page: StreamPage, icon: Radio, title: "Stream", hint: "Live chat and karaoke (experimental)" },
  "brain": { page: BrainPage, icon: Brain, title: "Brain", hint: "Language model, personality and sampling" },
  "tts": { page: TTSPage, icon: AudioLines, title: "Voice", hint: "Voice engine and voice library" },
  "input": { page: InputPage, icon: Mic, title: "Microphone", hint: "Speech recognition input" },
  "vision": { page: VisionPage, icon: MonitorPlay, title: "Screen", hint: "Screen capture, OCR and captions" },
  "memory": { page: MemoryPage, icon: Database, title: "Memory", hint: "Chat sessions and long-term memory", unmountWhenHidden: true },
  "pipeline-monitor": { page: PipelineMonitorPage, icon: SquareActivity, title: "Pipeline", hint: "Debug the LLM → voice pipeline" },
  "settings": { page: SettingsPage, icon: Settings, title: "Settings", hint: "App settings, tokens and folders" },
} satisfies Record<string, PageConfig>

export type PageKey = keyof typeof pageMapping

export const navGroups: { label: string; keys: PageKey[] }[] = [
  { label: "Live", keys: ["llm", "character", "stream"] },
  { label: "Setup", keys: ["brain", "tts", "input", "vision", "memory"] },
  { label: "Advanced", keys: ["pipeline-monitor", "settings"] },
]

export default pageMapping as Record<PageKey, PageConfig>
