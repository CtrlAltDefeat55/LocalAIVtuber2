import { Card, CardContent } from "@/components/ui/card";
import { useEffect, useState } from "react";
import { ttsManager } from "@/lib/ttsManager";
import { RVCProvider } from "@/lib/tts/rvcProvider";
import SettingDropdown from "./setting-dropdown";
import SettingSwitch from "./setting-switch";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import SettingSlider from "./setting-slider";

export default function RvcSettings() {
    const [rvcModels, setRvcModels] = useState<string[]>([]);
    const [edgeModels, setEdgeModels] = useState<string[]>([]);
    const [downloadUrl, setDownloadUrl] = useState("");
    const [isDownloading, setIsDownloading] = useState(false);
    const provider = ttsManager.getProvider<RVCProvider>("rvc");

    useEffect(() => {
        // Initial state
        setRvcModels(provider.getVoices());
        setEdgeModels(provider.getEdgeVoices());

        // Subscribe to changes
        const unsubscribe = provider.subscribe(() => {
            setRvcModels(provider.getVoices());
            setEdgeModels(provider.getEdgeVoices());
        });

        return unsubscribe;
    }, [provider]);

    const handleRvcModelChange = async (modelName: string) => {
        if (modelName) {
            try {
                await provider.setVoice(modelName);
            } catch (error) {
                console.error('Failed to load RVC model:', error);
                toast.error("Failed to load RVC model");
            }
        }
    }

    const handleEdgeModelChange = (modelName: string) => {
        if (modelName) {
            provider.setEdgeVoice(modelName);
        }
    }

    const handleDownload = async () => {
        if (!downloadUrl.trim()) {
            toast.error("Please enter a download URL");
            return;
        }

        setIsDownloading(true);
        try {
            const result = await provider.downloadModel(downloadUrl);
            toast.success(
                `Model '${result.model_name}' downloaded successfully${!result.has_index ? " (no index file found)" : ""}`
            );
            setDownloadUrl(""); // Clear the input
        } catch (error) {
            console.error('Failed to download model:', error);
            toast.error(error instanceof Error ? error.message : "Failed to download model");
        } finally {
            setIsDownloading(false);
        }
    }

    // Convert model arrays to options objects
    const rvcOptions = Object.fromEntries(rvcModels.map(model => [model, model]));
    const edgeOptions = Object.fromEntries(edgeModels.map(model => [model, model]));

    const handlePitchChange = (value: number) => {
        provider.setF0UpKey(value);
    }

    const handleUseRVCChange = (value: boolean) => {
        provider.setUseRVC(value);
    }

    return (
        <div className="space-y-2">
            <Card>
                <CardContent className="space-y-6">
                    <div className="flex space-x-4">
                        <SettingDropdown
                            id="tts.rvc.edge-tts-model"
                            defaultValue={edgeModels[0]}
                            label="Edge TTS Model"
                            options={edgeOptions}
                            onValueChange={handleEdgeModelChange}
                        />

                        <SettingDropdown
                            id="tts.rvc.model"
                            defaultValue={rvcModels[0]}
                            label="RVC Model"
                            options={rvcOptions}
                            onValueChange={handleRvcModelChange}
                        />
                    </div>
                    <div className="flex space-x-4">
                        <SettingSwitch id="rvc.use-rvc" label="Use RVC" description="Turn off to skip RVC processing" onClick={handleUseRVCChange} />
                        <SettingSlider id="rvc.f0-up-key" label="Pitch" description="F0_Up_Key" min={-50} max={50} step={1} defaultValue={0} onChange={handlePitchChange}  />
                    </div>
                    <div className="flex flex-col space-y-4">
                        <Label>RVC Model Downloader</Label>
                        <p className="text-sm text-muted-foreground">
                            Go to https://voice-models.com/ and paste the download link here.
                        </p>
                        <div className="flex space-x-4">    
                            <Input 
                                value={downloadUrl}
                                onChange={(e) => setDownloadUrl(e.target.value)}
                                placeholder="Enter model download URL"
                                disabled={isDownloading}
                            />
                            <Button 
                                onClick={handleDownload}
                                disabled={isDownloading || !downloadUrl.trim()}
                            >
                                {isDownloading ? "Downloading..." : "Download"}
                            </Button>
                        </div>
                    </div>
                </CardContent>
            </Card>
        </div>
    )
}