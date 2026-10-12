import React from "react";
import { Label } from "@/components/ui/label";
import { useSettings } from "@/context/SettingsContext";
import { Textarea } from "./ui/textarea";
import { cn } from "@/lib/utils";

interface SettingsTextboxProps {
    id: string;
    label: string;
    description?: string;
    placeholder?: string;
    className?: string;
    rows?: number;
}

const SettingTextbox: React.FC<SettingsTextboxProps> = ({ id, label, description, placeholder, className, rows = 6 }) => {
    const { settings, updateSetting } = useSettings();

    return (
        <div className={cn("flex flex-col items-start gap-2 w-full", className)}>
            <Label htmlFor={id} className="text-sm font-medium">{label}</Label>
            {description && <p className="text-[13px] text-muted-foreground -mt-1">{description}</p>}
            <Textarea
                id={id}
                rows={rows}
                value={settings[id] ?? ""}
                onChange={(e) => updateSetting(id, e.target.value)}
                placeholder={placeholder}
                className="resize-y leading-relaxed"
            />
        </div>
    );
};

export default SettingTextbox;
