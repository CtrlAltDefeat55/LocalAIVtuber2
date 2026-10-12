import { useState } from "react"
import { Edit3, Save, X, Trash, ArrowRight, RotateCcw } from "lucide-react"
import { Button } from "./ui/button"
import { Textarea } from "./ui/textarea"
import { HistoryItem } from "@/lib/types"
import { TooltipContent, TooltipTrigger } from "./ui/tooltip"
import { Tooltip } from "./ui/tooltip"
import { TooltipProvider } from "./ui/tooltip"
import { toast } from "sonner"

interface EditableChatHistoryProps {
    messages: HistoryItem[]
    sessionId: string
    onUpdate: (updatedHistory: HistoryItem[]) => void
    onContinue: (index: number) => void
    onRegenerate: (index: number) => void
}

export default function EditableChatHistory({ messages, sessionId, onUpdate, onContinue, onRegenerate }: EditableChatHistoryProps) {
    const [editingMessageIndex, setEditingMessageIndex] = useState<number | null>(null)
    const [editContent, setEditContent] = useState("")

    const startEditing = (index: number) => {
        setEditingMessageIndex(index)
        setEditContent(messages[index].content)
    }

    const continueMessage = (index: number) => {
        onContinue(index)
    }

    const regenerateMessage = (index: number) => {
        onRegenerate(index)
    }

    const deleteMessage = async (index: number) => {
        try {
            const updatedHistory = [...messages]
            updatedHistory.splice(index, 1)

            const response = await fetch(`/api/chat/session/update`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    session_id: sessionId,
                    history: updatedHistory
                }),
            })

            if (!response.ok) {
                throw new Error('Failed to update message')
            }

            onUpdate(updatedHistory)
        } catch (err) {
            toast.error(err instanceof Error ? err.message : 'Failed to update message')
        }
    }

    const saveEdit = async () => {
        if (editingMessageIndex === null) return

        try {
            const updatedHistory = [...messages]
            updatedHistory[editingMessageIndex] = {
                ...updatedHistory[editingMessageIndex],
                content: editContent
            }

            const response = await fetch(`/api/chat/session/update`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    session_id: sessionId,
                    history: updatedHistory
                }),
            })

            if (!response.ok) {
                throw new Error('Failed to update message')
            }

            onUpdate(updatedHistory)
            setEditingMessageIndex(null)
            setEditContent("")
        } catch (err) {
            toast.error(err instanceof Error ? err.message : 'Failed to update message')
        }
    }

    const cancelEdit = () => {
        setEditingMessageIndex(null)
        setEditContent("")
    }

    return (
        <div className="flex flex-col space-y-4">
            {messages.map((message, index) => (
                <div key={index} className="group relative flex flex-col gap-1.5">
                    <div className={`text-xs font-medium text-muted-foreground ${message.role === 'user'
                        ? 'self-end'
                        : 'self-start'
                    }`}>
                        {message.role === 'user' ? 'You' : 'VTuber'}
                    </div>
                    <div
                        className={`break-words max-w-[80%] w-fit px-4 py-2.5 text-[15px] leading-relaxed ${message.role === 'user'
                                ? 'self-end rounded-2xl rounded-br-md bg-primary text-primary-foreground'
                                : 'self-start rounded-2xl rounded-bl-md border bg-card text-card-foreground shadow-xs'
                            }`}
                    >
                        {editingMessageIndex === index ? (
                            <div className="space-y-3">
                                <Textarea
                                    value={editContent}
                                    onChange={(e) => setEditContent(e.target.value)}
                                    className="min-h-24"
                                />
                                <div className="flex space-x-2">
                                    <Button size="sm" onClick={saveEdit}>
                                        <Save className="h-4 w-4 mr-2" />
                                        Save
                                    </Button>
                                    <Button size="sm" variant="outline" onClick={cancelEdit}>
                                        <X className="h-4 w-4 mr-2" />
                                        Cancel
                                    </Button>
                                </div>
                            </div>
                        ) : (
                            <div className="whitespace-pre-wrap">{message.content || <span className="inline-flex gap-1 opacity-60"><span className="animate-pulse">●</span><span className="animate-pulse [animation-delay:150ms]">●</span><span className="animate-pulse [animation-delay:300ms]">●</span></span>}</div>
                        )}
                    </div>
                    {editingMessageIndex !== index && (
                        <div className={`-mt-1 flex opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity ${message.role === 'user'
                                ? 'self-end ml-auto'
                                : 'self-start mr-auto'
                            }`}>
                            <TooltipProvider>
                                <Tooltip>
                                    <TooltipTrigger asChild>
                                        <Button variant="ghost" size="sm" aria-label="Continue this message" onClick={() => continueMessage(index)}>
                                            <ArrowRight className="h-4 w-4" />
                                        </Button>
                                    </TooltipTrigger>
                                    <TooltipContent side="bottom" sideOffset={14}>
                                        Continue this message
                                    </TooltipContent>
                                </Tooltip>
                            </TooltipProvider>
                            {message.role === 'assistant' && (
                                <TooltipProvider>
                                    <Tooltip>
                                        <TooltipTrigger asChild>
                                            <Button variant="ghost" size="sm" aria-label="Regenerate reply" onClick={() => regenerateMessage(index)}>
                                                <RotateCcw className="h-4 w-4" />
                                            </Button>
                                        </TooltipTrigger>
                                        <TooltipContent side="bottom" sideOffset={14}>
                                            Regenerate reply
                                        </TooltipContent>
                                    </Tooltip>
                                </TooltipProvider>
                            )}
                            <TooltipProvider>
                                <Tooltip>
                                    <TooltipTrigger asChild>
                                        <Button variant="ghost" size="sm" aria-label="Edit message" onClick={() => startEditing(index)}>
                                            <Edit3 className="h-4 w-4" />
                                        </Button>
                                    </TooltipTrigger>
                                    <TooltipContent side="bottom" sideOffset={14}>
                                        Edit
                                    </TooltipContent>
                                </Tooltip>
                            </TooltipProvider>
                            <TooltipProvider>
                                <Tooltip>
                                    <TooltipTrigger asChild>
                                        <Button variant="ghost" size="sm" aria-label="Delete message" onClick={() => deleteMessage(index)}>
                                            <Trash className="h-4 w-4" />
                                        </Button>
                                    </TooltipTrigger>
                                    <TooltipContent side="bottom" sideOffset={14}>
                                        Delete
                                    </TooltipContent>
                                </Tooltip>
                            </TooltipProvider>
                        </div>
                    )}
                </div>
            ))}
        </div>
    )
} 