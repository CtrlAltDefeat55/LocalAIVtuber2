import { pipelineManager } from './pipelineManager';
import { globalStateManager } from './globalStateManager';
import { BaseTTSProvider } from './tts/baseTTSProvider';
import { LocalEngineProvider } from './tts/localEngineProvider';
import { RVCProvider } from './tts/rvcProvider';
import { toastErrorOnce } from './api';

export type TTSProvider = "local" | "rvc";
type TTSUpdateCallback = () => void;

/** Older settings stored "gpt-sovits"; that now means "the local voice engine". */
export function normalizeProvider(value: unknown): TTSProvider {
    return value === "rvc" ? "rvc" : "local";
}

export class TTSManager {
    private abortController: AbortController | null = null;
    private currentAudio: HTMLAudioElement | null = null;
    private isProcessing: boolean = false;
    private isPlaying: boolean = false;
    private selectedProvider: TTSProvider = "local";
    private speakingEnabled: boolean = true;
    private subscribers: Set<TTSUpdateCallback> = new Set();
    private providers: Record<TTSProvider, BaseTTSProvider>;
    // One AudioContext for the whole session: browsers cap how many can exist.
    private audioContext: AudioContext | null = null;
    private analyser: AnalyserNode | null = null;

    constructor() {
        this.providers = {
            "local": new LocalEngineProvider(),
            "rvc": new RVCProvider()
        };
        this.setupPipelineSubscription();
    }

    public subscribe(callback: TTSUpdateCallback): () => void {
        this.subscribers.add(callback);
        return () => this.subscribers.delete(callback);
    }

    private notifySubscribers() {
        this.subscribers.forEach(callback => callback());
    }

    public getSelectedProvider(): TTSProvider {
        return this.selectedProvider;
    }

    public setSelectedProvider(provider: TTSProvider | string) {
        this.selectedProvider = normalizeProvider(provider);
        this.notifySubscribers();
    }

    /** Text-only mode: replies still appear in chat but are not spoken. */
    public setSpeakingEnabled(enabled: boolean) {
        this.speakingEnabled = enabled;
        this.processNextTTS();
    }

    public getProvider<T extends BaseTTSProvider>(provider: TTSProvider): T {
        return this.providers[provider] as T;
    }

    public getCurrentProviderInstance(): BaseTTSProvider {
        return this.providers[this.selectedProvider];
    }

    private setupPipelineSubscription() {
        return pipelineManager.subscribe(() => {
            this.processNextTTS();
            this.processNextAudio();
        });
    }

    private connectAnalyser(audio: HTMLAudioElement) {
        if (!this.audioContext) {
            this.audioContext = new AudioContext();
            this.analyser = this.audioContext.createAnalyser();
            this.analyser.fftSize = 256;
            this.analyser.connect(this.audioContext.destination);
        }
        if (this.audioContext.state === "suspended") {
            this.audioContext.resume().catch(() => undefined);
        }
        const source = this.audioContext.createMediaElementSource(audio);
        source.connect(this.analyser!);

        const dataArray = new Uint8Array(this.analyser!.frequencyBinCount);
        const updateVolume = () => {
            this.analyser!.getByteFrequencyData(dataArray);
            const avgVolume = dataArray.reduce((a, b) => a + b, 0);
            globalStateManager.updateState("ttsLiveVolume", avgVolume / 15096);
            if (!audio.paused && !audio.ended) {
                requestAnimationFrame(updateVolume);
            } else {
                globalStateManager.updateState("ttsLiveVolume", 0);
                source.disconnect();
            }
        };
        updateVolume();
    }

    public async generateAudioFromText(text: string, provider: TTSProvider = this.selectedProvider): Promise<string> {
        const abortController = new AbortController();
        this.abortController = abortController;
        const response = await this.providers[provider].generateAudio(text, abortController.signal);
        const blob = await response.blob();
        return URL.createObjectURL(blob);
    }

    private async processNextTTS() {
        const currentTask = pipelineManager.getCurrentTask();
        if (currentTask?.status == "pending_interruption" && !currentTask.interruptionState?.tts) {
            if (this.abortController) {
                this.abortController.abort();
            }
            this.isProcessing = false;
            pipelineManager.markInterruptionState("tts");
            return;
        }
        
        if (this.isProcessing) return;

        const next = pipelineManager.getNextTaskForTTS();
        if (!next) return;

        const { taskId, responseIndex, task } = next;
        const textToSpeak = task.response[responseIndex].text;

        if (!this.speakingEnabled) {
            pipelineManager.markTTSFailed(taskId, responseIndex); // skip quietly
            return;
        }

        this.isProcessing = true;

        try {
            const audioUrl = await this.generateAudioFromText(textToSpeak);
            this.isProcessing = false;
            pipelineManager.addTTSAudio(taskId, responseIndex, audioUrl);
        } catch (err) {
            this.isProcessing = false;
            if ((err as Error).name === "AbortError") return;
            console.error("TTS pipeline error:", err);
            toastErrorOnce(`Voice: ${(err as Error).message}`, { label: "Open Voice", page: "tts" });
            // Skip this sentence instead of retrying forever; the text stays in the chat.
            pipelineManager.markTTSFailed(taskId, responseIndex);
        }
    }

    private async processNextAudio() {
        const currentTask = pipelineManager.getCurrentTask();
        if (currentTask?.status == "pending_interruption" && !currentTask.interruptionState?.audio) {
            if (this.currentAudio) {
                this.currentAudio.pause();
                this.currentAudio.currentTime = 0;
                this.currentAudio = null;
            }
            this.isPlaying = false;
            globalStateManager.updateState("ttsLiveVolume", 0);
            pipelineManager.markInterruptionState("audio");
            return;
        }

        if (this.isPlaying) return;

        const next = pipelineManager.getNextTaskForAudio();
        if (!next) return;

        const { taskId, responseIndex, task } = next;

        const audioUrl = task.response[responseIndex].audio;
        this.isPlaying = true;

        const audio = new Audio(audioUrl!);
        this.currentAudio = audio;
        const finish = () => {
            if (this.currentAudio !== audio) return;
            this.isPlaying = false;
            this.currentAudio = null;
            URL.revokeObjectURL(audioUrl!);
            pipelineManager.markPlaybackFinished(taskId, responseIndex);
        };
        audio.onended = finish;
        audio.onerror = finish;
        this.connectAnalyser(audio);
        audio.play().catch((err) => {
            console.error("Audio playback failed:", err);
            toastErrorOnce("The browser blocked audio playback. Click anywhere in the app, then try again.");
            finish();
        });
    }
}

export const ttsManager = new TTSManager();
