import clsx from "clsx";
import { Menu } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Sidebar, type View } from "./components/Sidebar";
import { Button, ErrorNotice } from "./components/ui";
import { ExecutionPanel } from "./features/agent/ExecutionPanel";
import { ChatView } from "./features/chat/ChatView";
import { DocumentsView } from "./features/documents/DocumentsView";
import { EvaluationView } from "./features/evaluation/EvaluationView";
import { SettingsView } from "./features/settings/SettingsView";
import { useAsync } from "./hooks/useAsync";
import { useChat } from "./hooks/useChat";
import { useTheme } from "./hooks/useTheme";
import { api, ApiError } from "./services/api";
import type { Mode, ToolName } from "./types/api";

const ALL_TOOLS: ToolName[] = ["document_retrieval", "web_search", "sql_query", "calculator"];

export default function App() {
  const { theme, toggle } = useTheme();
  const [view, setView] = useState<View>("chat");
  const [mode, setMode] = useState<Mode>("document_rag");
  const [tools, setTools] = useState<ToolName[]>(ALL_TOOLS);
  const [navOpen, setNavOpen] = useState(false);
  // The execution panel is docked on wide screens and an overlay on small ones.
  const [panelOpen, setPanelOpen] = useState(() => window.matchMedia?.("(min-width: 1280px)").matches ?? false);
  const [inspectedId, setInspectedId] = useState<string | undefined>();
  const [appError, setAppError] = useState<ApiError | null>(null);

  const health = useAsync(() => api.health(), []);
  const sessions = useAsync(() => api.sessions(), []);
  const docs = useAsync(() => api.documents(), []);
  const chat = useChat(useCallback(() => void sessions.reload(), [sessions.reload]));

  // Follow the latest assistant message in the execution panel.
  const lastAssistant = [...chat.messages].reverse().find((m) => m.role === "assistant");
  useEffect(() => {
    if (lastAssistant) setInspectedId(lastAssistant.id);
  }, [lastAssistant?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!chat.busy) void sessions.reload();
  }, [chat.busy]); // eslint-disable-line react-hooks/exhaustive-deps

  const inspected = chat.messages.find((m) => m.id === inspectedId) ?? lastAssistant;

  const go = (v: View) => {
    setView(v);
    setNavOpen(false);
  };

  const selectSession = async (id: string) => {
    try {
      await chat.load(id);
      go("chat");
    } catch (err) {
      setAppError(err as ApiError);
    }
  };

  const deleteSession = async (id: string) => {
    try {
      await api.deleteSession(id);
      if (chat.sessionId === id) chat.reset();
      await sessions.reload();
    } catch (err) {
      setAppError(err as ApiError);
    }
  };

  return (
    <div className="flex h-full overflow-hidden">
      {/* Sidebar: static on desktop, drawer on mobile */}
      <div
        className={clsx(
          "fixed inset-y-0 left-0 z-30 w-72 border-r border-border transition-transform lg:static lg:translate-x-0",
          navOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <Sidebar
          view={view}
          onView={go}
          sessions={sessions.data ?? []}
          activeSession={chat.sessionId}
          onSelectSession={(id) => void selectSession(id)}
          onDeleteSession={(id) => void deleteSession(id)}
          onNewChat={() => {
            chat.reset();
            go("chat");
          }}
          health={health.data}
          healthLoading={health.loading}
          theme={theme}
          onToggleTheme={toggle}
        />
      </div>
      {navOpen && (
        <button
          aria-label="Close menu"
          className="fixed inset-0 z-20 bg-black/50 lg:hidden"
          onClick={() => setNavOpen(false)}
        />
      )}

      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 border-b border-border px-3 py-2 lg:hidden">
          <Button variant="ghost" size="icon" onClick={() => setNavOpen(true)} aria-label="Open menu">
            <Menu className="h-5 w-5" />
          </Button>
          <span className="text-sm font-semibold">Open-Source AI Playground</span>
        </div>
        {appError && (
          <div className="p-3">
            <ErrorNotice message={appError.message} hint={appError.hint} />
            <Button size="sm" variant="ghost" onClick={() => setAppError(null)}>
              Dismiss
            </Button>
          </div>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto">
          {view === "chat" && (
            <ChatView
              messages={chat.messages}
              busy={chat.busy}
              mode={mode}
              onModeChange={setMode}
              enabledTools={tools}
              onToolsChange={setTools}
              onSend={(q) => void chat.send(q, mode, tools)}
              onStop={chat.stop}
              onRetry={chat.retry}
              onFeedback={(id, r) => void chat.setFeedback(id, r)}
              onInspect={(id) => {
                setInspectedId(id);
                setPanelOpen(true);
              }}
              onClear={() => {
                if (chat.sessionId) void deleteSession(chat.sessionId);
                else chat.reset();
              }}
              onTogglePanel={() => setPanelOpen((o) => !o)}
              inspectedId={inspected?.id}
              documentCount={docs.data?.length}
            />
          )}
          {view === "documents" && <DocumentsView onChange={() => void docs.reload()} />}
          {view === "evaluation" && <EvaluationView />}
          {view === "settings" && <SettingsView health={health.data} onHealthReload={() => void health.reload()} />}
        </div>
      </main>

      {view === "chat" && panelOpen && (
        <div className="fixed inset-y-0 right-0 z-30 w-full max-w-md border-l border-border shadow-xl xl:static xl:w-96 xl:shadow-none">
          <ExecutionPanel message={inspected} onClose={() => setPanelOpen(false)} availableTools={tools} />
        </div>
      )}
      {view === "chat" && panelOpen && (
        <button
          aria-label="Close execution details overlay"
          className="fixed inset-0 z-20 bg-black/40 xl:hidden"
          onClick={() => setPanelOpen(false)}
        />
      )}
    </div>
  );
}
