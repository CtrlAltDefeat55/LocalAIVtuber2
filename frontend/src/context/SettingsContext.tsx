/* eslint-disable @typescript-eslint/no-explicit-any */
import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { readError } from "@/lib/api";

interface SettingsContextType {
    settings: Record<string, any>;
    /** Updates the UI immediately; persists to the backend (debounced for rapid changes like typing). */
    updateSetting: (key: string, value: any, options?: { immediate?: boolean }) => Promise<void>;
    /** True only while the very first load is in progress. */
    loading: boolean;
    /** True while a change is waiting to be saved. */
    saving: boolean;
}

const SettingsContext = createContext<SettingsContextType | undefined>(undefined);
const SAVE_DELAY_MS = 400;

export const SettingsProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [settings, setSettings] = useState<Record<string, any>>({});
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const pending = useRef<Record<string, any>>({});
    const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
    const waiters = useRef<Array<() => void>>([]);

    useEffect(() => {
        const fetchSettings = async () => {
            try {
                const response = await fetch('/api/settings');
                if (!response.ok) throw new Error(await readError(response));
                const data = await response.json();
                setSettings(data.settings || {});
            } catch (error) {
                console.error("Error fetching settings:", error);
                toast.error("Could not load settings from the app backend.");
            } finally {
                setLoading(false);
            }
        };
        fetchSettings();
    }, []);

    const flush = useCallback(async () => {
        timer.current = null;
        const batch = pending.current;
        pending.current = {};
        const resolve = waiters.current;
        waiters.current = [];
        if (Object.keys(batch).length === 0) {
            resolve.forEach(r => r());
            return;
        }
        try {
            const response = await fetch('/api/settings/update', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ settings: batch }),
            });
            if (!response.ok) throw new Error(await readError(response));
        } catch (error) {
            console.error("Error updating settings:", error);
            toast.error(`Setting not saved: ${(error as Error).message}`);
        } finally {
            if (!timer.current) setSaving(false);
            resolve.forEach(r => r());
        }
    }, []);

    const updateSetting = useCallback((key: string, value: any, options?: { immediate?: boolean }) => {
        setSettings((prev) => ({ ...prev, [key]: value }));
        pending.current[key] = value;
        setSaving(true);
        if (timer.current) clearTimeout(timer.current);
        const done = new Promise<void>((resolve) => waiters.current.push(resolve));
        timer.current = setTimeout(flush, options?.immediate ? 0 : SAVE_DELAY_MS);
        return done;
    }, [flush]);

    // Never lose a debounced change when the window closes.
    useEffect(() => {
        const onUnload = () => {
            if (Object.keys(pending.current).length) {
                navigator.sendBeacon('/api/settings/update',
                    new Blob([JSON.stringify({ settings: pending.current })], { type: 'application/json' }));
            }
        };
        // pagehide (not beforeunload) never delays or blocks closing/reloading the window
        window.addEventListener('pagehide', onUnload);
        return () => window.removeEventListener('pagehide', onUnload);
    }, []);

    return (
        <SettingsContext.Provider value={{ settings, updateSetting, loading, saving }}>
            {children}
        </SettingsContext.Provider>
    );
};

export const useSettings = (): SettingsContextType => {
    const context = useContext(SettingsContext);
    if (!context) {
        throw new Error("useSettings must be used within a SettingsProvider");
    }
    return context;
};
