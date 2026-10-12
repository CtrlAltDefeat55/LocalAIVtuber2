import React, { useEffect, useState } from "react";
import { Slider } from "@/components/ui/slider";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { useSettings } from "@/context/SettingsContext";
import { cn } from "@/lib/utils";

interface SettingsSliderProps {
    id: string;
    label: string;
    description?: string;
    min?: number;
    max?: number;
    step?: number;
    defaultValue?: number;
    /** Unit shown after the number, e.g. "%" or "×". */
    unit?: string;
    className?: string;
    onChange?: (value: number) => void;
}

const decimals = (step: number) => (String(step).split(".")[1] || "").length;

/** Slider with a synced number field. Both edit the same stored value; typing is validated on commit. */
const SettingSlider: React.FC<SettingsSliderProps> = ({
    id, label, description, min = 0, max = 100, step = 1, defaultValue = 0, unit, className = "", onChange
}) => {
    const { settings, updateSetting } = useSettings();
    const stored = settings[id] !== undefined && settings[id] !== "" ? Number(settings[id]) : defaultValue;
    const currentValue = Number.isFinite(stored) ? stored : defaultValue;
    const [draft, setDraft] = useState(currentValue.toFixed(decimals(step)));

    useEffect(() => {
        setDraft(currentValue.toFixed(decimals(step)));
    }, [currentValue, step]);

    const commit = (value: number) => {
        const clamped = Math.min(max, Math.max(min, value));
        const rounded = Number((Math.round(clamped / step) * step).toFixed(decimals(step)));
        updateSetting(id, rounded);
        onChange?.(rounded);
        setDraft(rounded.toFixed(decimals(step)));
    };

    const commitDraft = () => {
        const parsed = parseFloat(draft);
        if (Number.isFinite(parsed)) commit(parsed);
        else setDraft(currentValue.toFixed(decimals(step)));
    };

    return (
        <div className={cn("flex flex-col gap-2 w-full", className)}>
            <div className="flex items-center justify-between gap-3">
                <Label htmlFor={id} className="text-sm font-medium">{label}</Label>
                <div className="flex items-center gap-1">
                    <Input
                        aria-label={`${label} value`}
                        className="h-7 w-20 text-right tabular font-mono text-xs"
                        inputMode="decimal"
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        onBlur={commitDraft}
                        onKeyDown={(e) => {
                            if (e.key === "Enter") commitDraft();
                            if (e.key === "Escape") setDraft(currentValue.toFixed(decimals(step)));
                            if (e.key === "ArrowUp") { e.preventDefault(); commit(currentValue + step); }
                            if (e.key === "ArrowDown") { e.preventDefault(); commit(currentValue - step); }
                        }}
                    />
                    {unit && <span className="text-xs text-muted-foreground w-4">{unit}</span>}
                </div>
            </div>
            <Slider
                id={id}
                min={min}
                max={max}
                step={step}
                value={[currentValue]}
                onValueChange={(value) => commit(value[0])}
                className="w-full"
            />
            {description && <p className="text-xs leading-snug text-muted-foreground">{description}</p>}
        </div>
    );
};

export default SettingSlider;
