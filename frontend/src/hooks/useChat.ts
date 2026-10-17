import { useCallback, useRef, useState } from "react";
import { api, ApiError } from "../services/api";
import type { ChatResponse, ExecutionStep, Mode, SessionDetail, Source, ToolName } from "../types/api";

export interface UiMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  mode: Mode;
  status: "streaming" | "done" | "error" | "cancelled";
  /** Final structured response (set when the run completes). */
  response?: ChatResponse;
  /** Live trace while streaming. */
  steps: ExecutionStep[];
  sources: Source[];
  statusText?: string;
  error?: { message: string; hint?: string; code: string };
  /** For retry. */
  request?: { question: string; mode: Mode; enabledTools: ToolName[] };
  serverMessageId?: string | null;
  feedback?: number | null;
}

let counter = 0;
const localId = () => `local-${Date.now()}-${counter++}`;

function upsertStep(steps: ExecutionStep[], step: ExecutionStep): ExecutionStep[] {
  const i = steps.findIndex((s) => s.id === step.id);
  if (i === -1) return [...steps, step];
  const next = steps.slice();
  next[i] = step;
  return next;
}

export function fromSession(detail: SessionDetail): UiMessage[] {
  return detail.messages.map((m) => {
    const meta = m.meta;
    const response: ChatResponse | undefined =
      m.role === "assistant" && meta
        ? ({ ...meta, answer: m.content, session_id: detail.id, message_id: m.id } as ChatResponse)
        : undefined;
    return {
      id: m.id,
      role: m.role,
      content: m.content,
      mode: (m.mode ?? "direct") as Mode,
      status: m.status === "error" ? "error" : m.status === "cancelled" ? "cancelled" : "done",
      response,
      steps: response?.steps ?? [],
      sources: response?.sources ?? [],
      serverMessageId: m.role === "assistant" ? m.id : null,
      feedback: m.feedback,
      error:
        m.status === "error" && response?.errors?.length
          ? { message: response.errors[response.errors.length - 1].message, code: response.errors[0].code }
          : undefined,
    };
  });
}

export function useChat(onSessionChange?: (id: string) => void) {
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const patch = useCallback((id: string, fn: (m: UiMessage) => UiMessage) => {
    setMessages((prev) => prev.map((m) => (m.id === id ? fn(m) : m)));
  }, []);

  const send = useCallback(
    async (question: string, mode: Mode, enabledTools: ToolName[]) => {
      if (!question.trim() || busy) return;
      const userMsg: UiMessage = {
        id: localId(),
        role: "user",
        content: question,
        mode,
        status: "done",
        steps: [],
        sources: [],
      };
      const assistantId = localId();
      const assistant: UiMessage = {
        id: assistantId,
        role: "assistant",
        content: "",
        mode,
        status: "streaming",
        steps: [],
        sources: [],
        statusText: "Starting…",
        request: { question, mode, enabledTools },
      };
      setMessages((prev) => [...prev, userMsg, assistant]);
      setBusy(true);
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        const stream = api.streamChat(
          { session_id: sessionId, question, mode, enabled_tools: mode === "agent" ? enabledTools : [] },
          controller.signal,
        );
        for await (const ev of stream) {
          switch (ev.type) {
            case "session":
              if (ev.session_id && ev.session_id !== sessionId) {
                setSessionId(ev.session_id);
                onSessionChange?.(ev.session_id);
              }
              patch(assistantId, (m) => ({ ...m, serverMessageId: ev.message_id }));
              break;
            case "status":
              patch(assistantId, (m) => ({ ...m, statusText: ev.message }));
              break;
            case "tool_start":
              patch(assistantId, (m) => ({
                ...m,
                steps: upsertStep(m.steps, ev.step),
                statusText: ev.step.purpose ?? `Running ${ev.step.name}`,
              }));
              break;
            case "tool_end":
              patch(assistantId, (m) => ({ ...m, steps: upsertStep(m.steps, ev.step) }));
              break;
            case "sources":
              patch(assistantId, (m) => ({ ...m, sources: ev.sources }));
              break;
            case "delta":
              patch(assistantId, (m) => ({ ...m, content: m.content + ev.text, statusText: undefined }));
              break;
            case "done":
              patch(assistantId, (m) => ({
                ...m,
                status: "done",
                content: ev.response.answer,
                response: ev.response,
                steps: ev.response.steps,
                sources: ev.response.sources,
                statusText: undefined,
              }));
              break;
            case "error":
              patch(assistantId, (m) => ({
                ...m,
                status: "error",
                content: ev.response?.answer || m.content,
                response: ev.response,
                steps: ev.response?.steps ?? m.steps,
                sources: ev.response?.sources ?? m.sources,
                error: { message: ev.error.message, hint: ev.error.hint, code: ev.error.code },
                statusText: undefined,
              }));
              break;
          }
        }
      } catch (err) {
        if ((err as Error).name === "AbortError") {
          patch(assistantId, (m) => ({ ...m, status: "cancelled", statusText: undefined }));
        } else {
          const e = err instanceof ApiError ? err : new ApiError(0, { code: "error", message: String(err) });
          patch(assistantId, (m) => ({
            ...m,
            status: "error",
            statusText: undefined,
            error: { message: e.message, hint: e.hint, code: e.code },
          }));
        }
      } finally {
        abortRef.current = null;
        setBusy(false);
      }
    },
    [busy, sessionId, patch, onSessionChange],
  );

  const stop = useCallback(() => abortRef.current?.abort(), []);

  const retry = useCallback(
    (assistantId: string) => {
      const msg = messages.find((m) => m.id === assistantId);
      if (!msg?.request) return;
      // Drop the failed exchange and resend.
      setMessages((prev) => {
        const i = prev.findIndex((m) => m.id === assistantId);
        return prev.slice(0, Math.max(0, i - 1)).concat(prev.slice(i + 1));
      });
      void send(msg.request.question, msg.request.mode, msg.request.enabledTools);
    },
    [messages, send],
  );

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setMessages([]);
    setSessionId(null);
  }, []);

  const load = useCallback(async (id: string) => {
    abortRef.current?.abort();
    const detail = await api.session(id);
    setSessionId(id);
    setMessages(fromSession(detail));
  }, []);

  const setFeedback = useCallback(
    async (localMessageId: string, rating: 1 | -1) => {
      const msg = messages.find((m) => m.id === localMessageId);
      if (!msg?.serverMessageId) return;
      await api.feedback(msg.serverMessageId, rating);
      patch(localMessageId, (m) => ({ ...m, feedback: rating }));
    },
    [messages, patch],
  );

  return { messages, sessionId, busy, send, stop, retry, reset, load, setFeedback };
}
