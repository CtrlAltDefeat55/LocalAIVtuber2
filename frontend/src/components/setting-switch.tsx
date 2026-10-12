import React from "react";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { useSettings } from "@/context/SettingsContext";
import { cn } from "@/lib/utils";

interface SettingsSwitchProps {
    id: string;
    label: string;
    description?: React.ReactNode;
    className?: string;
    disabled?: boolean;
    /** Shown under the description when the switch is disabled, explaining why. */
    disabledReason?: React.ReactNode;
    onClick?: (value: boolean) => void;
}

const SettingSwitch: React.FC<SettingsSwitchProps> = ({ id, label, description, className = "", disabled, disabledReason, onClick }) => {
    const { settings, updateSetting } = useSettings();

    return (
        <div className={cn("flex items-start justify-between gap-6 w-full py-1", className)}>
            <div className="space-y-1 min-w-0">
                <Label htmlFor={id} className={cn("text-sm font-medium", disabled && "opacity-60")}>{label}</Label>
                {description && <p className="text-[13px] leading-snug text-muted-foreground">{description}</p>}
                {disabled && disabledReason && <p className="text-[13px] leading-snug text-warning">{disabledReason}</p>}
            </div>
            <Switch
                id={id}
                className="mt-0.5 shrink-0"
                disabled={disabled}
                checked={Boolean(settings[id])}
                onCheckedChange={(value) => {
                    updateSetting(id, value, { immediate: true });
                    onClick?.(value);
                }}
            />
        </div>
    );
};

export default SettingSwitch;
