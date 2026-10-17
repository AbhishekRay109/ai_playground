import { PanelRight, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "../../components/ui";
import type { UiMessage } from "../../hooks/useChat";
import { modeInfo } from "../../lib/modes";
import type { Mode, ToolName } from "../../types/api";
import { Composer } from "./Composer";
import { MessageBubble } from "./MessageBubble";
import { AgentToolToggles, ModeSelector } from "./ModeSelector";

export interface ChatViewProps {
  messages: UiMessage[];
  busy: boolean;
  mode: Mode;
  onModeChange: (m: Mode) => void;
  enabledTools: ToolName[];
  onToolsChange: (t: ToolName[]) => void;
  onSend: (q: string) => void;
  onStop: () => void;
  onRetry: (id: string) => void;
  onFeedback: (id: string, rating: 1 | -1) => void;
  onInspect: (id: string) => void;
  onClear: () => void;
  onTogglePanel: () => void;
  inspectedId?: string;
  documentCount?: number;
}

export function ChatView(p: ChatViewProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const last = p.messages[p.messages.length - 1];
  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [p.messages.length, last?.content.length]);

  const info = modeInfo(p.mode);
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="space-y-2 border-b border-border px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">Execution mode</h2>
          <div className="flex items-center gap-1">
            {p.messages.length > 0 &&
              (confirmClear ? (
                <span className="flex items-center gap-1 text-xs">
                  Delete this conversation?
                  <Button
                    size="sm"
                    variant="danger"
                    onClick={() => {
                      setConfirmClear(false);
                      p.onClear();
                    }}
                  >
                    Delete
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setConfirmClear(false)}>
                    Cancel
                  </Button>
                </span>
              ) : (
                <Button size="sm" variant="ghost" onClick={() => setConfirmClear(true)} disabled={p.busy}>
                  <Trash2 className="h-3.5 w-3.5" /> Clear conversation
                </Button>
              ))}
            <Button size="sm" variant="ghost" onClick={p.onTogglePanel} aria-label="Toggle execution details">
              <PanelRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
        <ModeSelector value={p.mode} onChange={p.onModeChange} />
        {p.mode === "agent" && <AgentToolToggles enabled={p.enabledTools} onChange={p.onToolsChange} />}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4" aria-live="polite">
        {p.messages.length === 0 ? (
          <div className="mx-auto max-w-2xl py-8 text-center">
            <Sparkles className="mx-auto h-8 w-8 text-accent" aria-hidden />
            <h2 className="mt-3 text-lg font-semibold">{info.label}</h2>
            <p className="mt-1 text-sm text-muted">{info.description}</p>
            {p.mode === "document_rag" && p.documentCount === 0 && (
              <p className="mt-2 text-xs text-warn">No documents uploaded yet. Add some in the Documents page.</p>
            )}
            <div className="mt-5 grid gap-2 text-left sm:grid-cols-3">
              {info.examples.map((ex) => (
                <button
                  key={ex}
                  type="button"
                  onClick={() => p.onSend(ex)}
                  className="rounded-xl border border-border bg-surface p-3 text-sm hover:border-accent/60 focus-visible:outline-2 focus-visible:outline-accent"
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mx-auto max-w-3xl space-y-4">
            {p.messages.map((m) => (
              <MessageBubble
                key={m.id}
                message={m}
                selected={m.id === p.inspectedId}
                onInspect={m.role === "assistant" ? () => p.onInspect(m.id) : undefined}
                onRetry={m.role === "assistant" ? () => p.onRetry(m.id) : undefined}
                onFeedback={m.role === "assistant" ? (r) => p.onFeedback(m.id, r) : undefined}
              />
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      <div className="border-t border-border px-4 py-3">
        <div className="mx-auto max-w-3xl">
          <Composer mode={p.mode} enabledTools={p.enabledTools} busy={p.busy} onSend={p.onSend} onStop={p.onStop} />
        </div>
      </div>
    </div>
  );
}
