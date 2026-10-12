export abstract class BaseTTSProvider {
    abstract generateAudio(text: string, signal?: AbortSignal): Promise<Response>;
}
