import { ArrowUp, Square } from "lucide-react";
import { useState, type KeyboardEvent } from "react";
import { Badge, Button } from "../../components/ui";
import { modeInfo, toolLabel } from "../../lib/modes";
import type { Mode, ToolName } from "../../types/api";

export function Composer({
  mode,
  enabledTools,
  busy,
  onSend,
  onStop,
  maxChars = 4000,
}: {
  mode: Mode;
  enabledTools: ToolName[];
  busy: boolean;
  onSend: (q: string) => void;
  onStop: () => void;
  maxChars?: number;
}) {
  const [text, setText] = useState("");
  const submit = () => {
    const q = text.trim();
    if (!q || busy) return;
    onSend(q);
    setText("");
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };
  const info = modeInfo(mode);
  return (
    <form
      className="rounded-2xl border border-border bg-surface p-2 shadow-sm focus-within:border-accent/60"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <label htmlFor="question" className="sr-only">
        Question
      </label>
      <textarea
        id="question"
        value={text}
        onChange={(e) => setText(e.target.value.slice(0, maxChars))}
        onKeyDown={onKey}
        rows={2}
        placeholder={`Ask a question (${info.label})…  Enter to send, Shift+Enter for a new line`}
        className="block max-h-48 min-h-[3rem] w-full resize-y bg-transparent px-2 py-1.5 text-sm outline-none placeholder:text-muted"
      />
      <div className="flex flex-wrap items-center justify-between gap-2 px-1 pt-1">
        <div className="flex min-w-0 flex-wrap items-center gap-1.5" data-testid="mode-indicator">
          <Badge tone="accent">Mode: {info.label}</Badge>
          {mode === "agent" &&
            (enabledTools.length ? (
              enabledTools.map((t) => <Badge key={t}>{toolLabel(t)}</Badge>)
            ) : (
              <Badge tone="warn">No tools enabled</Badge>
            ))}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-muted">
            {text.length}/{maxChars}
          </span>
          {busy ? (
            <Button variant="danger" size="sm" onClick={onStop} aria-label="Stop generating">
              <Square className="h-3.5 w-3.5" /> Stop
            </Button>
          ) : (
            <Button type="submit" variant="primary" size="sm" disabled={!text.trim()} aria-label="Send">
              <ArrowUp className="h-4 w-4" /> Send
            </Button>
          )}
        </div>
      </div>
    </form>
  );
}
