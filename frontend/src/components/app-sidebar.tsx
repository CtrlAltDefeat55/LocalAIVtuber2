import pageMapping, { navGroups, PageKey } from "@/constants/page-mapping"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar"
import { ModeToggle } from "./mode-toggle"
import { Button } from "@/components/ui/button"
import { Power } from "lucide-react"
import { useSystemStatus } from "@/context/SystemStatusContext"
import { StatusDot, Tone } from "./layout"
import { useConfirm } from "./confirm-dialog"
import appIcon from "@/assets/app-icon.svg"
import { cn } from "@/lib/utils"

function brainTone(state?: string, downloaded?: boolean, runtime?: boolean, remote?: boolean): [Tone, string] {
  if (remote) return state === "ready" ? ["ok", "API connected"] : state === "error" ? ["error", "API error"] : ["warn", "API not set up"]
  if (runtime === false) return ["error", "Runtime missing"]
  if (!downloaded) return ["warn", "No model downloaded"]
  switch (state) {
    case "ready": return ["ok", "Ready"]
    case "loading": return ["busy", "Loading model…"]
    case "error": return ["error", "Error"]
    default: return ["off", "Not loaded"]
  }
}

function voiceTone(state?: string, remote?: boolean): [Tone, string] {
  if (remote) return state === "ready" ? ["ok", "Service connected"] : state === "error" ? ["error", "Service error"] : ["warn", "Not set up"]
  switch (state) {
    case "ready": return ["ok", "Ready"]
    case "starting": return ["busy", "Starting…"]
    case "installing": return ["busy", "Installing…"]
    case "error": return ["error", "Error"]
    case "not_installed": return ["warn", "Not installed"]
    default: return ["off", "Stopped"]
  }
}

export function AppSidebar({ onItemClick, activePage }: { onItemClick: (key: PageKey) => void, activePage?: PageKey }) {
  const { status, connected } = useSystemStatus()
  const { state } = useSidebar()
  const collapsed = state === "collapsed"
  const { confirm, dialog } = useConfirm()
  const [bTone, bLabel] = brainTone(status?.llm.state, status?.llm.model_downloaded, status?.llm.runtime_installed, status?.llm.provider === "remote")
  const [vTone, vLabel] = voiceTone(status?.tts.state, !!status?.tts.source && status.tts.source !== "local")

  const quit = async () => {
    const ok = await confirm({
      title: "Quit Local AI VTuber?",
      description: "This stops the language model, the voice engine and the app server, and frees the GPU memory they use. Your settings and chats are already saved.",
      confirmLabel: "Quit app",
    })
    if (!ok) return
    try {
      await fetch("/api/system/shutdown", { method: "POST" })
    } finally {
      window.close() // works for the dedicated app window; a normal browser tab shows the disconnected screen
    }
  }

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-3 pt-4 pb-2">
        <div className="flex items-center gap-2.5 overflow-hidden">
          <img src={appIcon} alt="" className="size-8 shrink-0 rounded-lg" />
          {!collapsed && (
            <div className="min-w-0 leading-tight">
              <div className="truncate text-sm font-semibold">Local AI VTuber</div>
              <div className="truncate text-[11px] text-muted-foreground">
                {connected ? `v${status?.version ?? "…"} · runs on your PC` : "Disconnected"}
              </div>
            </div>
          )}
        </div>
      </SidebarHeader>

      <SidebarContent>
        {navGroups.map((group) => (
          <SidebarGroup key={group.label}>
            <SidebarGroupLabel>{group.label}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {group.keys.map((key) => {
                  const Icon = pageMapping[key].icon
                  const badge = key === "brain" ? bTone : key === "tts" ? vTone : null
                  return (
                    <SidebarMenuItem key={key}>
                      <SidebarMenuButton
                        isActive={key === activePage}
                        tooltip={`${pageMapping[key].title} — ${pageMapping[key].hint}`}
                        onClick={() => onItemClick(key)}
                      >
                        <Icon />
                        <span>{pageMapping[key].title}</span>
                        {badge && badge !== "ok" && !collapsed && (
                          <span className={cn("ml-auto size-2 rounded-full",
                            badge === "error" ? "bg-destructive" : badge === "busy" ? "bg-primary animate-pulse" : "bg-warning")} />
                        )}
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  )
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>

      <SidebarFooter className="gap-2 pb-3">
        {!collapsed && (
          <div className="rounded-xl border bg-background/40 p-3 space-y-2">
            <button className="flex w-full items-center justify-between text-left hover:opacity-80" onClick={() => onItemClick("brain")}>
              <span className="text-xs font-medium">Brain</span>
              <StatusDot tone={connected ? bTone : "error"} label={<span className="text-muted-foreground">{connected ? bLabel : "Offline"}</span>} />
            </button>
            <button className="flex w-full items-center justify-between text-left hover:opacity-80" onClick={() => onItemClick("tts")}>
              <span className="text-xs font-medium">Voice</span>
              <StatusDot tone={connected ? vTone : "error"} label={<span className="text-muted-foreground">{connected ? vLabel : "Offline"}</span>} />
            </button>
          </div>
        )}
        <div className={cn("flex items-center gap-1", collapsed ? "flex-col" : "justify-between")}>
          <ModeToggle />
          <Button variant="ghost" size={collapsed ? "icon" : "sm"} onClick={quit} title="Quit the app and free GPU memory"
            className="text-muted-foreground hover:text-destructive">
            <Power className="size-4" />
            {!collapsed && <span>Quit</span>}
          </Button>
        </div>
      </SidebarFooter>
      <SidebarRail />
      {dialog}
    </Sidebar>
  )
}
