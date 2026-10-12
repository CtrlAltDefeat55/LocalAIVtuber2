import { useEffect, useState } from "react";
import { ExternalLink, FolderOpen, KeyRound, Loader2, Settings } from "lucide-react";
import { toast } from "sonner";
import { PageBody, PageHeader, Section } from "@/components/layout";
import SettingSwitch from "@/components/setting-switch";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSettings } from "@/context/SettingsContext";
import { useSystemStatus } from "@/context/SystemStatusContext";
import { api } from "@/lib/api";

const FOLDERS: [string, string, string][] = [
    ["app", "App folder", "Everything: runtimes, models, voices, settings. Move this folder to move the whole app."],
    ["models", "Language models", "Downloaded .gguf files. Drop your own .gguf here and it shows up on the Brain page."],
    ["voices", "Voices", "Reference recordings for voice cloning."],
    ["live2d", "Live2D models", "2D character folders."],
    ["vrm", "VRM models", "3D character files."],
];

function TokenSection() {
    const [hint, setHint] = useState<string | null>(null);
    const [hasToken, setHasToken] = useState(false);
    const [value, setValue] = useState("");
    const [saving, setSaving] = useState(false);

    const load = () => api<{ has_token: boolean; hint: string | null }>("/api/settings/hf-token")
        .then((d) => { setHasToken(d.has_token); setHint(d.hint); }).catch(() => undefined);
    useEffect(() => { load(); }, []);

    const save = async (token: string | null) => {
        setSaving(true);
        try {
            await api("/api/settings/hf-token", { method: "POST", json: { token } });
            toast.success(token ? "Token saved" : "Token removed");
            setValue("");
            await load();
        } catch (e) {
            toast.error((e as Error).message);
        } finally {
            setSaving(false);
        }
    };

    return (
        <Section title="Hugging Face access" description="Only needed for gated models (TADA voices, some LLMs). Everything else downloads without an account.">
            <div className="space-y-3">
                <div className="flex items-center gap-2 text-sm">
                    <KeyRound className="size-4 text-muted-foreground" />
                    {hasToken ? <span>Token saved <span className="font-mono text-muted-foreground">{hint}</span></span> : <span className="text-muted-foreground">No token saved</span>}
                </div>
                <div className="flex gap-2">
                    <Label htmlFor="hf-token" className="sr-only">Hugging Face token</Label>
                    <Input id="hf-token" type="password" autoComplete="off" placeholder="hf_…" value={value}
                        onChange={(e) => setValue(e.target.value)} onKeyDown={(e) => e.key === "Enter" && value.trim() && save(value)} className="max-w-md" />
                    <Button onClick={() => save(value)} disabled={!value.trim() || saving}>{saving ? <Loader2 className="animate-spin" /> : null} Save token</Button>
                    {hasToken && <Button variant="outline" onClick={() => save(null)} disabled={saving}>Remove</Button>}
                </div>
                <p className="text-xs text-muted-foreground">
                    Create a free “read” token at{" "}
                    <a className="inline-flex items-center gap-0.5 text-primary hover:underline" href="https://huggingface.co/settings/tokens" target="_blank" rel="noreferrer">
                        huggingface.co/settings/tokens <ExternalLink className="size-3" />
                    </a>, then accept the license on each gated model's page. The token is stored only inside the app folder (cache/huggingface/token) and is never sent anywhere except Hugging Face.
                </p>
            </div>
        </Section>
    );
}

function SettingsPage() {
    const { loading } = useSettings();
    const { status } = useSystemStatus();

    if (loading) return null;

    const open = (which: string) => api("/api/system/open-folder", { method: "POST", json: { which } }).catch((e) => toast.error(e.message));

    return (
        <PageBody>
            <PageHeader icon={Settings} title="Settings" description="App-wide preferences. Model and voice options live on the Brain and Voice pages." />
            <div className="space-y-6">
                <Section title="Conversation">
                    <div className="space-y-3">
                        <SettingSwitch id="tts.enabled" label="Speak replies out loud"
                            description="Turn off for text-only chat (useful for testing prompts without waiting for the voice)." />
                    </div>
                </Section>

                <TokenSection />

                <Section title="Storage" description="All app data stays in one folder, so you can move the app to another drive and keep everything.">
                    <div className="divide-y rounded-xl border">
                        {FOLDERS.map(([key, title, text]) => (
                            <div key={key} className="flex items-center justify-between gap-4 px-4 py-3">
                                <div className="min-w-0">
                                    <div className="text-sm font-medium">{title}</div>
                                    <div className="text-xs text-muted-foreground">{text}</div>
                                </div>
                                <Button variant="outline" size="sm" onClick={() => open(key)}><FolderOpen /> Open</Button>
                            </div>
                        ))}
                    </div>
                </Section>

                <Section title="About">
                    <dl className="grid grid-cols-[10rem_1fr] gap-y-2 text-sm">
                        <dt className="text-muted-foreground">Version</dt><dd>{status?.version ?? "…"}</dd>
                        <dt className="text-muted-foreground">Graphics</dt>
                        <dd>{status ? (status.gpu.kind === "cuda" ? `NVIDIA ${status.gpu.name ?? ""}` : status.gpu.kind === "mps" ? "Apple Silicon (Metal)" : "CPU only") : "…"}</dd>
                        <dt className="text-muted-foreground">System</dt><dd>{status?.platform === "win32" ? "Windows" : status?.platform === "darwin" ? "macOS" : status?.platform ?? "…"}</dd>
                    </dl>
                </Section>
            </div>
        </PageBody>
    );
}

export default SettingsPage;
