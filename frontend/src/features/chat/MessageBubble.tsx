import clsx from "clsx";
import { Check, Copy, PanelRightOpen, RotateCcw, ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import { Badge, Button, ErrorNotice, Spinner } from "../../components/ui";
import type { UiMessage } from "../../hooks/useChat";
import { modeInfo, toolLabel } from "../../lib/modes";
import { Markdown } from "./Markdown";
import { SourceList } from "./SourceList";

export function MessageBubble({
  message,
  selected,
  onInspect,
  onRetry,
  onFeedback,
}: {
  message: UiMessage;
  selected?: boolean;
  onInspect?: () => void;
  onRetry?: () => void;
  onFeedback?: (rating: 1 | -1) => void;
}) {
  const [copied, setCopied] = useState(false);
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-accent-soft px-4 py-2.5 text-sm">
          {message.content}
        </div>
      </div>
    );
  }
  const r = message.response;
  const executed = r?.executed_tools ?? [
    ...new Set(message.steps.filter((s) => s.kind === "tool" && s.status !== "rejected").map((s) => s.name)),
  ];
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };
  const streaming = message.status === "streaming";
  return (
    <article
      aria-label="Assistant answer"
      className={clsx(
        "rounded-2xl border bg-surface px-4 py-3",
        selected ? "border-accent/60" : "border-border",
      )}
    >
      <header className="mb-1 flex flex-wrap items-center gap-1.5 text-xs">
        <Badge tone="accent">{modeInfo(message.mode).label}</Badge>
        {executed.map((t) => (
          <Badge key={t} tone="ok" title="Tool actually executed">
            ran: {toolLabel(t)}
          </Badge>
        ))}
        {r && <span className="text-muted">{(r.latency_ms / 1000).toFixed(1)}s</span>}
        {r?.status === "partial" && <Badge tone="warn">partial</Badge>}
        {message.status === "cancelled" && <Badge tone="warn">stopped</Badge>}
      </header>

      {streaming && message.statusText && (
        <p className="flex items-center gap-2 py-1 text-xs text-muted" aria-live="polite">
          <Spinner className="h-3.5 w-3.5" label="Working" /> {message.statusText}
        </p>
      )}
      {message.content ? (
        <div className={clsx(streaming && "cursor-blink")}>
          <Markdown text={message.content} />
        </div>
      ) : (
        streaming && !message.statusText && <Spinner label="Generating" />
      )}
      {message.status === "error" && message.error && (
        <div className="mt-2">
          <ErrorNotice
            title={message.content ? "The run did not finish" : "Request failed"}
            message={message.error.message}
            hint={message.error.hint}
            onRetry={onRetry}
          />
        </div>
      )}
      {r?.warnings?.length ? (
        <ul className="mt-2 space-y-0.5 text-xs text-warn">
          {r.warnings.map((w, i) => (
            <li key={i}>⚠ {w}</li>
          ))}
        </ul>
      ) : null}

      <SourceList sources={message.sources} compact />

      {!streaming && (
        <footer className="mt-2 flex flex-wrap items-center gap-1">
          <Button variant="ghost" size="sm" onClick={copy} aria-label="Copy answer" disabled={!message.content}>
            {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
            {copied ? "Copied" : "Copy"}
          </Button>
          {onInspect && (
            <Button variant="ghost" size="sm" onClick={onInspect} aria-label="Show execution details">
              <PanelRightOpen className="h-3.5 w-3.5" /> Trace
            </Button>
          )}
          {onRetry && message.status !== "done" && message.request && (
            <Button variant="ghost" size="sm" onClick={onRetry}>
              <RotateCcw className="h-3.5 w-3.5" /> Retry
            </Button>
          )}
          {onFeedback && message.serverMessageId && message.status === "done" && (
            <span className="ml-auto flex items-center gap-0.5">
              <Button
                variant="ghost"
                size="icon"
                aria-label="Good answer"
                aria-pressed={message.feedback === 1}
                className={clsx(message.feedback === 1 && "text-ok")}
                onClick={() => onFeedback(1)}
              >
                <ThumbsUp className="h-3.5 w-3.5" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                aria-label="Bad answer"
                aria-pressed={message.feedback === -1}
                className={clsx(message.feedback === -1 && "text-err")}
                onClick={() => onFeedback(-1)}
              >
                <ThumbsDown className="h-3.5 w-3.5" />
              </Button>
            </span>
          )}
        </footer>
      )}
    </article>
  );
}
