import clsx from "clsx";
import { FileStack, FlaskConical, MessageSquarePlus, MessagesSquare, Moon, Settings, Sun, Trash2 } from "lucide-react";
import type { HealthResponse, SessionSummary } from "../types/api";
import { modeInfo } from "../lib/modes";
import { Button, SectionTitle, StatusDot } from "./ui";

export type View = "chat" | "documents" | "evaluation" | "settings";

const NAV: { id: View; label: string; icon: typeof MessagesSquare }[] = [
  { id: "chat", label: "Chat", icon: MessagesSquare },
  { id: "documents", label: "Documents", icon: FileStack },
  { id: "evaluation", label: "Evaluation", icon: FlaskConical },
  { id: "settings", label: "Models & settings", icon: Settings },
];

const SERVICE_LABELS: Record<string, string> = {
  llm: "Ollama LLM",
  embeddings: "Embeddings",
  vector_store: "Qdrant",
  web_search: "SearXNG",
  sql_demo_db: "Sample DB",
};

export function Sidebar({
  view,
  onView,
  sessions,
  activeSession,
  onSelectSession,
  onDeleteSession,
  onNewChat,
  health,
  healthLoading,
  theme,
  onToggleTheme,
}: {
  view: View;
  onView: (v: View) => void;
  sessions: SessionSummary[];
  activeSession: string | null;
  onSelectSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
  onNewChat: () => void;
  health?: HealthResponse;
  healthLoading: boolean;
  theme: "dark" | "light";
  onToggleTheme: () => void;
}) {
  return (
    <nav aria-label="Main" className="flex h-full flex-col gap-4 bg-surface p-3">
      <div className="flex items-center gap-2 px-1">
        <img src="/logo.svg" alt="" className="h-8 w-8" />
        <div className="min-w-0">
          <h1 className="truncate text-sm font-semibold">Open-Source AI Playground</h1>
          <p className="text-[11px] text-muted">RAG · Web · SQL · Agents · Local LLMs</p>
        </div>
      </div>

      <Button variant="primary" onClick={onNewChat} className="w-full">
        <MessageSquarePlus className="h-4 w-4" /> New chat
      </Button>

      <ul className="space-y-0.5">
        {NAV.map((n) => (
          <li key={n.id}>
            <button
              type="button"
              onClick={() => onView(n.id)}
              aria-current={view === n.id ? "page" : undefined}
              className={clsx(
                "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-sm",
                view === n.id ? "bg-surface-2 font-medium" : "text-muted hover:bg-surface-2 hover:text-fg",
              )}
            >
              <n.icon className="h-4 w-4" aria-hidden /> {n.label}
            </button>
          </li>
        ))}
      </ul>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <SectionTitle>Conversations</SectionTitle>
        {sessions.length === 0 ? (
          <p className="px-1 text-xs text-muted">No conversations yet.</p>
        ) : (
          <ul className="space-y-0.5">
            {sessions.map((s) => (
              <li key={s.id} className="group flex items-center">
                <button
                  type="button"
                  onClick={() => onSelectSession(s.id)}
                  className={clsx(
                    "min-w-0 flex-1 rounded-lg px-2 py-1.5 text-left text-sm",
                    activeSession === s.id ? "bg-surface-2" : "hover:bg-surface-2",
                  )}
                >
                  <span className="block truncate">{s.title}</span>
                  <span className="block text-[11px] text-muted">
                    {s.last_mode ? modeInfo(s.last_mode).label : ""} · {s.message_count} msgs
                  </span>
                </button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="opacity-60 group-hover:opacity-100"
                  aria-label={`Delete conversation ${s.title}`}
                  onClick={() => onDeleteSession(s.id)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="rounded-lg border border-border p-2">
        <SectionTitle
          action={
            <Button
              variant="ghost"
              size="icon"
              onClick={onToggleTheme}
              aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            >
              {theme === "dark" ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
            </Button>
          }
        >
          System status
        </SectionTitle>
        <ul className="space-y-1">
          {Object.entries(SERVICE_LABELS).map(([key, label]) => {
            const s = health?.services[key];
            return (
              <li key={key} className="flex items-center gap-2 text-xs" title={s ? `${s.detail}${s.hint ? `\n${s.hint}` : ""}` : ""}>
                <StatusDot ok={s?.ok} pending={healthLoading && !s} />
                <span className="flex-1">{label}</span>
                <span className="text-muted">{s ? (s.ok ? "ready" : "unavailable") : healthLoading ? "…" : "unknown"}</span>
              </li>
            );
          })}
        </ul>
      </div>
    </nav>
  );
}
