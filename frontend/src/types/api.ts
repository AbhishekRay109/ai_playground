// Types mirroring the backend Pydantic schemas (backend/app/schemas).

export type Mode = "document_rag" | "web_search" | "sql" | "agent" | "direct";
export type ToolName = "document_retrieval" | "web_search" | "sql_query" | "calculator";
export type StepStatus = "running" | "success" | "error" | "timeout" | "rejected" | "skipped";

export interface RequestSettings {
  model?: string;
  temperature?: number;
  max_tokens?: number;
  top_k?: number;
  score_threshold?: number;
  search_results?: number;
  document_ids?: string[];
}

export interface ChatRequest {
  session_id?: string | null;
  question: string;
  mode: Mode;
  enabled_tools: ToolName[];
  settings?: RequestSettings;
}

export interface ExecutionStep {
  id: string;
  kind: "tool" | "llm" | "system";
  name: string;
  status: StepStatus;
  purpose?: string | null;
  input_summary?: string | null;
  result_summary?: string | null;
  latency_ms?: number | null;
  retries: number;
  details: Record<string, unknown>;
}

export interface Source {
  id: number;
  kind: "document" | "web" | "sql";
  title: string;
  excerpt: string;
  cited: boolean;
  document_id?: string | null;
  filename?: string | null;
  page?: number | null;
  chunk_id?: string | null;
  chunk_index?: number | null;
  score?: number | null;
  url?: string | null;
  content_type?: "page" | "snippet" | null;
  engine?: string | null;
  published_date?: string | null;
  sql?: string | null;
  row_count?: number | null;
}

export interface ChatResponse {
  session_id: string | null;
  message_id: string | null;
  mode: Mode;
  status: "success" | "partial" | "error" | "cancelled";
  answer: string;
  model?: string | null;
  embedding_model?: string | null;
  available_tools: string[];
  selected_tools: string[];
  executed_tools: string[];
  steps: ExecutionStep[];
  sources: Source[];
  counts: { retrieved_chunks: number; web_sources: number; sql_rows: number; tool_calls: number };
  citations: { total_markers: number; valid_markers: number; invalid_markers: number[] };
  token_usage: { prompt_tokens: number; completion_tokens: number; estimated: boolean };
  latency_ms: number;
  errors: { code: string; message: string; step?: string }[];
  warnings: string[];
  created_at?: string | null;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  hint?: string;
  retryable?: boolean;
  details?: { field: string; message: string }[];
}

export type StreamEvent =
  | { type: "session"; session_id: string | null; message_id: string }
  | { type: "status"; message: string }
  | { type: "tool_start"; step: ExecutionStep }
  | { type: "tool_end"; step: ExecutionStep }
  | { type: "sources"; sources: Source[] }
  | { type: "delta"; text: string }
  | { type: "done"; response: ChatResponse }
  | { type: "error"; error: ApiErrorBody; response?: ChatResponse };

export interface DocumentInfo {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  content_hash: string;
  page_count: number | null;
  chunk_count: number;
  char_count: number;
  embedding_model: string;
  status: string;
  stale: boolean;
  created_at: string;
}

export interface IngestResult {
  filename: string;
  status: "ready" | "duplicate" | "error";
  document_id?: string | null;
  chunk_count: number;
  page_count?: number | null;
  duplicate_of?: string | null;
  error?: string | null;
  latency_ms: number;
}

export interface SessionSummary {
  id: string;
  title: string;
  last_mode: Mode | null;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface MessageOut {
  id: string;
  role: "user" | "assistant";
  content: string;
  mode: Mode | null;
  status: string;
  meta: Omit<ChatResponse, "answer" | "session_id" | "message_id"> | null;
  feedback: number | null;
  created_at: string;
}

export interface SessionDetail extends SessionSummary {
  messages: MessageOut[];
}

export interface ModelInfo {
  name: string;
  size_bytes?: number | null;
  family?: string | null;
  parameter_size?: string | null;
  quantization?: string | null;
  modified_at?: string | null;
}

export interface ModelsResponse {
  available: boolean;
  models: ModelInfo[];
  current_model: string;
  error?: string | null;
  hint?: string | null;
}

export interface ServiceStatus {
  ok: boolean;
  detail: string;
  hint?: string | null;
  latency_ms?: number | null;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  version: string;
  services: Record<string, ServiceStatus>;
}

export interface RuntimeConfig {
  chat_model: string;
  temperature: number;
  max_tokens: number;
  llm_timeout_s: number;
  embedding_model: string;
  rag_top_k: number;
  rag_score_threshold: number;
}

export interface ConfigResponse {
  runtime: RuntimeConfig;
  embedding_provider: string;
  ollama_base_url: string;
  searxng_url: string;
  vector_store: string;
  limits: Record<string, number>;
  warnings: string[];
}

export interface CompareResult {
  mode: Mode;
  response?: ChatResponse | null;
  error?: ApiErrorBody | null;
}

export interface DatasetInfo {
  name: string;
  description: string;
  items: number;
  documents: string[];
  modes: string[];
}

export interface EvalItemResult {
  id: string;
  mode: string;
  question: string;
  status: string;
  answer?: string;
  error?: string;
  latency_ms?: number;
  executed_tools?: string[];
  sources?: number;
  retrieval_hit?: boolean | null;
  recall_at_k?: number | null;
  citation_validity?: number | null;
  completeness_estimate?: number | null;
  groundedness_estimate?: number | null;
  tool_selection_success?: boolean | null;
  task_completed?: boolean;
}

export interface EvalReport {
  dataset: string;
  run_at: string;
  model: string;
  embedding_model: string;
  duration_ms: number;
  summary: Record<string, number | null>;
  items: EvalItemResult[];
  notes: string[];
  markdown: string;
}
