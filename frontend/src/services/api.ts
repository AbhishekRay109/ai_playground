import type {
  ApiErrorBody,
  ChatRequest,
  ChatResponse,
  CompareResult,
  ConfigResponse,
  DatasetInfo,
  DocumentInfo,
  EvalReport,
  HealthResponse,
  IngestResult,
  Mode,
  ModelsResponse,
  RequestSettings,
  RuntimeConfig,
  SessionDetail,
  SessionSummary,
  StreamEvent,
  ToolName,
} from "../types/api";

const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "/api/v1";

export class ApiError extends Error {
  code: string;
  hint?: string;
  status: number;
  retryable: boolean;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.code = body.code;
    this.hint = body.hint;
    this.status = status;
    this.retryable = body.retryable ?? status >= 500;
  }
}

async function parseError(res: Response): Promise<ApiError> {
  try {
    const data = await res.json();
    if (data?.error?.message) return new ApiError(res.status, data.error);
  } catch {
    /* not JSON */
  }
  return new ApiError(res.status, { code: `http_${res.status}`, message: `Request failed (HTTP ${res.status}).` });
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, init);
  } catch {
    throw new ApiError(0, {
      code: "backend_unreachable",
      message: "Cannot reach the backend API.",
      hint: "Start it with `uvicorn app.main:app --reload` in the backend directory.",
      retryable: true,
    });
  }
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

/** Parse a Server-Sent Events byte stream into JSON events. */
export async function* parseSSE(stream: ReadableStream<Uint8Array>): AsyncGenerator<StreamEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const data = block
        .split("\n")
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).trimStart())
        .join("\n");
      if (data) yield JSON.parse(data) as StreamEvent;
    }
  }
}

export const api = {
  health: () => request<HealthResponse>("/health"),
  models: () => request<ModelsResponse>("/models"),
  config: () => request<ConfigResponse>("/config"),
  updateConfig: (update: Partial<RuntimeConfig>) => request<ConfigResponse>("/config", json("PUT", update)),
  resetConfig: () => request<ConfigResponse>("/config/reset", { method: "POST" }),

  chat: (req: ChatRequest) => request<ChatResponse>("/chat", json("POST", req)),

  async *streamChat(req: ChatRequest, signal?: AbortSignal): AsyncGenerator<StreamEvent> {
    let res: Response;
    try {
      res = await fetch(`${BASE}/chat/stream`, { ...json("POST", req), signal });
    } catch (err) {
      if ((err as Error).name === "AbortError") throw err;
      throw new ApiError(0, {
        code: "backend_unreachable",
        message: "Cannot reach the backend API.",
        hint: "Start it with `uvicorn app.main:app --reload` in the backend directory.",
        retryable: true,
      });
    }
    if (!res.ok || !res.body) throw await parseError(res);
    yield* parseSSE(res.body);
  },

  feedback: (messageId: string, rating: 1 | -1) =>
    request<void>(`/messages/${messageId}/feedback`, json("POST", { rating })),

  sessions: () => request<SessionSummary[]>("/sessions"),
  session: (id: string) => request<SessionDetail>(`/sessions/${id}`),
  deleteSession: (id: string) => request<void>(`/sessions/${id}`, { method: "DELETE" }),

  documents: () => request<DocumentInfo[]>("/documents"),
  uploadDocuments: (files: File[]) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    return request<{ results: IngestResult[] }>("/documents", { method: "POST", body: form });
  },
  deleteDocument: (id: string) => request<void>(`/documents/${id}`, { method: "DELETE" }),
  reindexDocument: (id: string) => request<DocumentInfo>(`/documents/${id}/reindex`, { method: "POST" }),

  compare: (question: string, modes: Mode[], enabled_tools: ToolName[], settings?: RequestSettings) =>
    request<CompareResult[]>("/evaluation/compare", json("POST", { question, modes, enabled_tools, settings })),
  datasets: () => request<DatasetInfo[]>("/evaluation/datasets"),
  runDataset: (dataset: string) => request<EvalReport>("/evaluation/run", json("POST", { dataset })),
};
