export interface CharacterModel {
    /** Folder name (Live2D) or file name (VRM) on disk. */
    name: string;
    path: string;
    displayName: string;
    /** Live2D only: referenced files (textures, .moc3) that are missing on disk. */
    missing?: string[];
}

export interface ModelResponse {
    models: CharacterModel[];
}

/**
 * Fetch available Live2D models from the backend
 */
export async function fetchLive2DModels(): Promise<CharacterModel[]> {
    try {
        const response = await fetch('/api/character/live2d/models');
        if (!response.ok) {
            throw new Error(`Failed to fetch Live2D models: ${response.statusText}`);
        }
        const data: ModelResponse = await response.json();
        return data.models;
    } catch (error) {
        console.error('Error fetching Live2D models:', error);
        return [];
    }
}

/**
 * Fetch available VRM models from the backend
 */
export async function fetchVRMModels(): Promise<CharacterModel[]> {
    try {
        const response = await fetch('/api/character/vrm/models');
        if (!response.ok) {
            throw new Error(`Failed to fetch VRM models: ${response.statusText}`);
        }
        const data: ModelResponse = await response.json();
        return data.models;
    } catch (error) {
        console.error('Error fetching VRM models:', error);
        return [];
    }
} 