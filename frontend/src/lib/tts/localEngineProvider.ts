import { BaseTTSProvider } from "./baseTTSProvider";
import { readError } from "../api";

/** Speaks through the voice engine selected on the Voice page (Chatterbox, LuxTTS, OmniVoice, ...). */
export class LocalEngineProvider extends BaseTTSProvider {
    async generateAudio(text: string, signal?: AbortSignal): Promise<Response> {
        const response = await fetch("/api/tts", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text }),
            signal,
        });
        if (!response.ok) {
            throw new Error(await readError(response));
        }
        return response;
    }
}
