import { ChevronLeft, ChevronRight } from "lucide-react";
import { ReactNode, useState } from "react";
import { ScrollArea } from "./ui/scroll-area";

interface SidePanelProps {
    children?: ReactNode;
    side?: "left" | "right";
    className?: string;
    isOpen?: boolean;
    width?: number;  // Changed to number for direct pixel value
    togglePosition?: number;
    toggleText?: {
        open: string;
        close: string;
    };
}

export function SidePanel({ 
    children, 
    className, 
    side = "right", 
    isOpen = false,
    width = 256,  // Default to 256px
    togglePosition = 20,
    toggleText
}: SidePanelProps) {
    const [isSidePanelOpen, setIsSidePanelOpen] = useState(isOpen);

    const toggleSidePanel = () => {
        setIsSidePanelOpen((prev) => (!prev));
    };

    const renderToggleContent = () => {
        if (toggleText) {
            const text = isSidePanelOpen ? toggleText.close : toggleText.open;
            return (
                <div className="[writing-mode:vertical-lr] [text-orientation:upright] tracking-tighter text-[0.8rem]">
                    {text}
                </div>
            );
        }
        return isSidePanelOpen 
            ? (side === "right" ? <ChevronRight /> : <ChevronLeft />)
            : (side === "right" ? <ChevronLeft /> : <ChevronRight />);
    };

    return (
        <div
            className={`absolute ${side === "right" ? "right-0" : "left-0"} top-0 h-full transition-transform duration-300 ${className || ''}`}
            style={{ 
                zIndex: 40,
                transform: isSidePanelOpen 
                    ? 'translateX(0)' 
                    : side === "right"
                        ? `translateX(${width}px)`
                        : `translateX(-${width}px)`
            }}
        >
            <button
                className={`absolute ${side === "right" ? "left-[-28px] rounded-l-lg border-r-0" : "right-[-28px] rounded-r-lg border-l-0"} border bg-sidebar text-muted-foreground shadow-sm hover:text-foreground ${toggleText ? 'px-1 py-2' : 'p-1'}`}
                style={{ top: `${togglePosition}px` }}
                onClick={toggleSidePanel}
                aria-expanded={isSidePanelOpen}
                aria-label={isSidePanelOpen ? "Close panel" : "Open panel"}
            >
                {renderToggleContent()}
            </button>
            <ScrollArea className={`h-full flex flex-col gap-2 items-start rounded-none bg-sidebar p-5 shadow-lg ${side === "right" ? "border-l" : "border-r"}`} style={{width: `${width}px`}}>
                {children}
            </ScrollArea>
        </div>
    );
}