import { BaseTTSProvider } from "./baseTTSProvider";

interface RVCModel {
    name: string;
    model_path: string;
    index_path: string | null;
}

interface DownloadModelResponse {
    message: string;
    model_name: string;
    has_index: boolean;
}

type RVCStateUpdateCallback = () => void;

export class RVCProvider extends BaseTTSProvider {
    private currentVoice: string | null = null;
    private currentEdgeVoice: string | null = null;
    private voices: string[] = [];
    private edgeVoices: string[] = [];
    private subscribers = new Set<RVCStateUpdateCallback>();
    private useRVC: boolean = true;
    private f0_up_key: number = 0;

    constructor() {
        super();
        this.initialize();
    }

    private async initialize() {
        await this.fetchVoices();
        await this.fetchEdgeVoices();
    }

    subscribe(callback: RVCStateUpdateCallback): () => void {
        this.subscribers.add(callback);
        return () => this.subscribers.delete(callback);
    }

    private notifySubscribers() {
        this.subscribers.forEach(callback => callback());
    }

    private async fetchVoices() {
        try {
            const response = await fetch('/api/rvc/models');
            if (!response.ok) return; // RVC plugin not installed
            const data = await response.json();
            this.voices = data.models.map((model: RVCModel) => model.name);
            this.notifySubscribers();
        } catch {
            /* RVC unavailable */
        }
    }

    private async fetchEdgeVoices() {
        try {
            const response = await fetch('/api/rvc/edge-models');
            if (!response.ok) return;
            const data = await response.json();
            this.edgeVoices = data.models;
            this.notifySubscribers();
        } catch {
            /* RVC unavailable */
        }
    }

    isAvailable(): boolean {
        return this.edgeVoices.length > 0 || this.voices.length > 0;
    }

    getVoices(): string[] {
        return this.voices;
    }

    getEdgeVoices(): string[] {
        return this.edgeVoices;
    }

    getCurrentVoice(): string | null {
        return this.currentVoice;
    }

    getCurrentEdgeVoice(): string | null {
        return this.currentEdgeVoice;
    }

    setUseRVC(value: boolean): void {
        this.useRVC = value;
        this.notifySubscribers();
    }

    setF0UpKey(value: number): void {
        this.f0_up_key = value;
        this.notifySubscribers();
    }

    async setVoice(voice: string): Promise<void> {
        const response = await fetch(`/api/rvc/load_model/${voice}`, {
            method: 'POST'
        });

        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.error || 'Failed to load RVC model');
        }

        this.currentVoice = voice;
        this.notifySubscribers();
    }

    setEdgeVoice(voice: string): void {
        this.currentEdgeVoice = voice;
        this.notifySubscribers();
    }

    async generateAudio(text: string, signal?: AbortSignal): Promise<Response> {
        if (!this.currentVoice || !this.currentEdgeVoice) {
            throw new Error("RVC model and Edge TTS voice must be selected");
        }

        const response = await fetch("/api/rvc/convert", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                text,
                voice: this.currentEdgeVoice,
                model_name: this.currentVoice,
                use_rvc: this.useRVC,
                f0_up_key: this.f0_up_key
            }),
            signal,
        });

        if (!response.ok) {
            throw new Error("RVC conversion failed");
        }

        return response;
    }

    async downloadModel(url: string): Promise<DownloadModelResponse> {
        const response = await fetch("/api/rvc/download_model", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to download model');
        }

        const data = await response.json();
        
        // Refresh the voice list after successful download
        await this.fetchVoices();
        
        return data;
    }
}