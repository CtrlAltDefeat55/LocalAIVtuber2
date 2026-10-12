import { useEffect, useState } from "react"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { AppSidebar } from "@/components/app-sidebar"
import pageMapping, { PageKey } from "@/constants/page-mapping"
import { SettingsProvider, useSettings } from "@/context/SettingsContext"
import { SystemStatusProvider, useSystemStatus } from "@/context/SystemStatusContext"
import { ttsManager } from "@/lib/ttsManager"
import { PowerOff } from "lucide-react"
import appIcon from "@/assets/app-icon.svg"

const PAGE_STORAGE_KEY = "lav.page"

function initialPage(): PageKey {
    try {
        const saved = localStorage.getItem(PAGE_STORAGE_KEY)
        if (saved && saved in pageMapping) return saved as PageKey
    } catch { /* storage unavailable */ }
    return "llm"
}

/** Keeps app-wide services in sync with saved settings, whichever page is open. */
function SettingsBridge() {
    const { settings } = useSettings()
    useEffect(() => {
        ttsManager.setSelectedProvider(settings["tts.provider"])
    }, [settings["tts.provider"]]) // eslint-disable-line react-hooks/exhaustive-deps
    useEffect(() => {
        ttsManager.setSpeakingEnabled(settings["tts.enabled"] !== false)
    }, [settings["tts.enabled"]]) // eslint-disable-line react-hooks/exhaustive-deps
    return null
}

function Disconnected() {
    return (
        <div className="fixed inset-0 z-50 grid place-items-center bg-background/95 backdrop-blur-sm">
            <div className="max-w-sm text-center space-y-3">
                <PowerOff className="mx-auto size-10 text-muted-foreground" />
                <h2 className="text-lg font-semibold">The app is not running</h2>
                <p className="text-sm text-muted-foreground">
                    Local AI VTuber was closed or stopped responding. Start it again from the desktop shortcut
                    or the start script; this page reconnects automatically.
                </p>
            </div>
        </div>
    )
}

function Shell() {
    const [currentPage, setCurrentPage] = useState<PageKey>(initialPage)
    const { connected } = useSystemStatus()
    const { loading } = useSettings()

    const navigate = (key: PageKey) => {
        setCurrentPage(key)
        try { localStorage.setItem(PAGE_STORAGE_KEY, key) } catch { /* ignore */ }
    }

    useEffect(() => {
        const handler = (e: Event) => {
            const key = (e as CustomEvent<string>).detail
            if (key in pageMapping) navigate(key as PageKey)
        }
        window.addEventListener("lav:navigate", handler)
        return () => window.removeEventListener("lav:navigate", handler)
    }, [])

    if (loading) {
        return (
            <div className="grid h-screen place-items-center">
                <div className="flex flex-col items-center gap-3 text-sm text-muted-foreground">
                    <img src={appIcon} alt="" className="size-12 animate-pulse rounded-xl" />
                    Starting Local AI VTuber…
                </div>
            </div>
        )
    }

    return (
        <>
            <SettingsBridge />
            <AppSidebar onItemClick={navigate} activePage={currentPage} />
            <SidebarInset className="h-screen overflow-hidden">
                <main className="relative flex-1 h-full">
                    {(Object.keys(pageMapping) as PageKey[]).map((key) => {
                        const { page: PageComponent, unmountWhenHidden } = pageMapping[key]
                        const isActive = currentPage === key
                        if (unmountWhenHidden) {
                            return isActive ? (
                                <div key={key} className="absolute inset-0"><PageComponent isActive /></div>
                            ) : null
                        }
                        // Keep live pages (character renderer, pipeline) mounted but shrunk to 1px,
                        // so hidden WebGL canvases cost almost nothing to render.
                        return (
                            <div key={key} aria-hidden={!isActive}
                                className={isActive ? "absolute inset-0" : "absolute size-px overflow-hidden"}
                                style={isActive ? undefined : { visibility: "hidden", pointerEvents: "none" }}>
                                <PageComponent isActive={isActive} />
                            </div>
                        )
                    })}
                </main>
            </SidebarInset>
            {!connected && <Disconnected />}
        </>
    )
}

function Mainpage() {
    return (
        <SettingsProvider>
            <SystemStatusProvider>
                <SidebarProvider defaultOpen={!document.cookie.includes("sidebar_state=false")}>
                    <Shell />
                </SidebarProvider>
            </SystemStatusProvider>
        </SettingsProvider>
    );
}

export default Mainpage;
