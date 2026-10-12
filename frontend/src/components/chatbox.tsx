import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Send, Square, Plus, MoreHorizontal, Edit, Trash2, PanelLeftClose, PanelLeftOpen, MessagesSquare } from 'lucide-react';
import { useSettings } from '@/context/SettingsContext';
import EditableChatHistory from './editable-chat-history';
import { HistoryItem, Session } from '@/lib/types';
import { chatManager } from '@/lib/chatManager';
import { pipelineManager } from '@/lib/pipelineManager';
import { fetchSessions, createNewSession, deleteSession, updateSessionTitle } from '@/lib/sessionManager';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { useConfirm } from './confirm-dialog';
import { cn } from '@/lib/utils';

const SESSIONS_KEY = "lav.studio.sessions";

const Chatbox = ({ header }: { header?: React.ReactNode }) => {
    const [displayedMessages, setDisplayedMessages] = useState<HistoryItem[]>([]);
    const [input, setInput] = useState('');
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const [isProcessing, setIsProcessing] = useState(false);
    const [pipelineBusy, setPipelineBusy] = useState(false);
    const inputRef = useRef<HTMLTextAreaElement>(null);
    const { settings } = useSettings();
    const [sessionList, setSessionList] = useState<Session[]>([]);
    const [selectedSession, setSelectedSession] = useState<string | null>(null);
    const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
    const [editingTitle, setEditingTitle] = useState<string>('');
    const [showSessions, setShowSessions] = useState(() => {
        try { return localStorage.getItem(SESSIONS_KEY) !== "closed" } catch { return true }
    });
    const { confirm, dialog } = useConfirm();

    const getSessions = async () => {
        const data = await fetchSessions();
        setSessionList(data);
        if (data.length > 0 && !selectedSession) {
            setSelectedSession(data[0].id);
        } else if (data.length === 0 && selectedSession) {
            setSelectedSession(null);
        }
    };

    const handleCreateNewSession = async () => {
        const newSessionId = await createNewSession();
        if (newSessionId) {
            await getSessions();
            setSelectedSession(newSessionId);
        }
    };

    const handleDeleteSession = async (session: Session) => {
        const ok = await confirm({
            title: `Delete “${session.title}”?`,
            description: "The conversation and its memory index are removed. This cannot be undone.",
            confirmLabel: "Delete chat",
        });
        if (!ok) return;
        await deleteSession(session.id);
        const remaining = sessionList.filter(s => s.id !== session.id);
        if (selectedSession === session.id) setSelectedSession(remaining[0]?.id ?? null);
        await getSessions();
    };

    const saveEditing = async () => {
        if (editingSessionId && editingTitle.trim()) {
            if (await updateSessionTitle(editingSessionId, editingTitle.trim())) await getSessions();
        }
        setEditingSessionId(null);
        setEditingTitle('');
    };

    const isCurrentSessionEmpty = displayedMessages.length === 0;

    useEffect(() => { getSessions(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        if (selectedSession) chatManager.setSessionId(selectedSession);
    }, [selectedSession]);

    useEffect(() => {
        chatManager.setSystemPrompt(settings["llm.system_prompt"] ?? "");
    }, [settings["llm.system_prompt"]]); // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        chatManager.setEnableMemoryRetrieval(settings["llm.enableMemoryRetrieval"] ?? true);
    }, [settings["llm.enableMemoryRetrieval"]]); // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => chatManager.subscribe((messages) => setDisplayedMessages(messages), { onMessagesChange: true }), []);

    // The VTuber is "busy" while any task is generating or speaking.
    useEffect(() => pipelineManager.subscribe(() => setPipelineBusy(!!pipelineManager.getCurrentTask())), []);

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }, [displayedMessages]);

    const busy = isProcessing || pipelineBusy;

    const handleSend = async () => {
        const text = input.trim();
        if (!text) return;
        setIsProcessing(true);
        setInput('');
        try {
            await chatManager.sendMessage(text);
        } finally {
            setIsProcessing(false);
            inputRef.current?.focus();
            if (!selectedSession || sessionList.length === 0) {
                // the first message creates a session on the server; show it in the list
                const data = await fetchSessions();
                setSessionList(data);
                const current = chatManager.getSessionId();
                if (current) setSelectedSession(current);
            }
        }
    };

    const stop = () => {
        pipelineManager.interruptCurrentTask();
        chatManager.handleInterrupt();
    };

    return (
        <div className="flex h-full w-full">
            {showSessions && (
                <aside className="flex w-60 shrink-0 flex-col border-r bg-sidebar/50">
                    <div className="flex items-center justify-between gap-2 p-3">
                        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Chats</span>
                        <Button size="sm" variant="outline" onClick={handleCreateNewSession} disabled={busy || isCurrentSessionEmpty}
                            title={isCurrentSessionEmpty ? "The current chat is still empty" : "Start a new chat"}>
                            <Plus /> New
                        </Button>
                    </div>
                    <div className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
                        {sessionList.length === 0 && <p className="px-2 py-4 text-xs text-muted-foreground">Your conversations appear here.</p>}
                        {sessionList.map((session) => (
                            <div key={session.id} className="group relative">
                                {editingSessionId === session.id ? (
                                    <Input value={editingTitle} autoFocus className="h-8 text-sm"
                                        onChange={(e) => setEditingTitle(e.target.value)}
                                        onKeyDown={(e) => {
                                            if (e.key === 'Enter') saveEditing();
                                            if (e.key === 'Escape') { setEditingSessionId(null); setEditingTitle(''); }
                                        }}
                                        onBlur={saveEditing} />
                                ) : (
                                    <div className={cn("flex items-center rounded-lg pr-1 text-sm transition-colors",
                                        selectedSession === session.id ? "bg-accent text-accent-foreground" : "hover:bg-accent/50")}>
                                        <button className="min-w-0 flex-1 truncate px-2.5 py-2 text-left disabled:opacity-60"
                                            disabled={busy} onClick={() => setSelectedSession(session.id)}>
                                            {session.title}
                                        </button>
                                        <DropdownMenu>
                                            <DropdownMenuTrigger asChild>
                                                <Button variant="ghost" size="icon" className="size-7 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100"
                                                    aria-label={`Actions for ${session.title}`}>
                                                    <MoreHorizontal />
                                                </Button>
                                            </DropdownMenuTrigger>
                                            <DropdownMenuContent align="end">
                                                <DropdownMenuItem onClick={() => { setEditingSessionId(session.id); setEditingTitle(session.title); }}>
                                                    <Edit /> Rename
                                                </DropdownMenuItem>
                                                <DropdownMenuItem variant="destructive" onClick={() => handleDeleteSession(session)}>
                                                    <Trash2 /> Delete
                                                </DropdownMenuItem>
                                            </DropdownMenuContent>
                                        </DropdownMenu>
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                </aside>
            )}

            <div className="flex min-w-0 flex-1 flex-col">
                <div className="flex items-center gap-2 border-b px-4 py-2">
                    <Button variant="ghost" size="icon" className="size-8" onClick={() => {
                        setShowSessions((v) => {
                            try { localStorage.setItem(SESSIONS_KEY, v ? "closed" : "open") } catch { /* ignore */ }
                            return !v;
                        });
                    }} aria-label={showSessions ? "Hide chat list" : "Show chat list"}>
                        {showSessions ? <PanelLeftClose /> : <PanelLeftOpen />}
                    </Button>
                    <div className="min-w-0 flex-1">{header}</div>
                </div>

                <div className="flex-1 overflow-y-auto">
                    <div className="mx-auto max-w-3xl px-6 py-6">
                        {displayedMessages.length === 0 ? (
                            <div className="flex flex-col items-center gap-2 py-24 text-center text-muted-foreground">
                                <MessagesSquare className="size-10 opacity-40" />
                                <p className="text-base font-medium text-foreground">Say hi to your VTuber</p>
                                <p className="max-w-sm text-sm">Type below, or turn on the microphone on the Microphone page to talk out loud. Replies are spoken with the selected voice.</p>
                            </div>
                        ) : (
                            <EditableChatHistory
                                messages={displayedMessages}
                                sessionId={chatManager.getSessionId() ?? ""}
                                onUpdate={(history) => chatManager.setMessages(history)}
                                onContinue={(index) => chatManager.continueMessage(index)}
                                onRegenerate={(index) => chatManager.regenerateMessage(index)}
                            />
                        )}
                        <div ref={messagesEndRef} />
                    </div>
                </div>

                <div className="border-t bg-background/80 px-6 py-4 backdrop-blur">
                    <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-2xl border bg-card p-2 shadow-sm focus-within:ring-2 focus-within:ring-ring/40">
                        <Textarea
                            ref={inputRef}
                            rows={1}
                            value={input}
                            placeholder={busy ? "Your VTuber is talking… (Esc to stop)" : "Message your VTuber  (Enter to send, Shift+Enter for a new line)"}
                            onChange={(e) => setInput(e.target.value)}
                            onKeyDown={(e) => {
                                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                                    e.preventDefault();
                                    if (!busy) handleSend();
                                }
                                if (e.key === "Escape" && busy) stop();
                            }}
                            className="max-h-40 min-h-10 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0 dark:bg-transparent"
                        />
                        {busy ? (
                            <Button variant="secondary" onClick={stop} title="Stop the reply and the voice (Esc)">
                                <Square className="fill-current" /> Stop
                            </Button>
                        ) : (
                            <Button onClick={handleSend} disabled={!input.trim()} title="Send (Enter)">
                                <Send /> Send
                            </Button>
                        )}
                    </div>
                </div>
            </div>
            {dialog}
        </div>
    );
};

export default Chatbox;
