import type { ChatResponse, ExecutionStep } from "../types/api";

export const step = (over: Partial<ExecutionStep> = {}): ExecutionStep => ({
  id: "s1",
  kind: "tool",
  name: "calculator",
  status: "success",
  purpose: "compute",
  input_summary: "expression='129 * 347'",
  result_summary: "129 * 347 = 44763",
  latency_ms: 3,
  retries: 0,
  details: { expression: "129 * 347", result: 44763 },
  ...over,
});

export const response = (over: Partial<ChatResponse> = {}): ChatResponse => ({
  session_id: "sess-1",
  message_id: "msg-1",
  mode: "agent",
  status: "success",
  answer: "129 × 347 = **44763**.",
  model: "llama3.2:3b",
  embedding_model: null,
  available_tools: ["document_retrieval", "web_search", "sql_query", "calculator"],
  selected_tools: ["calculator"],
  executed_tools: ["calculator"],
  steps: [step()],
  sources: [],
  counts: { retrieved_chunks: 0, web_sources: 0, sql_rows: 0, tool_calls: 1 },
  citations: { total_markers: 0, valid_markers: 0, invalid_markers: [] },
  token_usage: { prompt_tokens: 50, completion_tokens: 10, estimated: false },
  latency_ms: 1234,
  errors: [],
  warnings: [],
  ...over,
});

/** Build a fetch Response whose body streams the given SSE events. */
export function sseResponse(events: object[]): Response {
  const text = events.map((e) => `event: ${(e as { type: string }).type}\ndata: ${JSON.stringify(e)}\n\n`).join("");
  const bytes = new TextEncoder().encode(text);
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      // Split across chunks to exercise buffering.
      const mid = Math.floor(bytes.length / 2);
      controller.enqueue(bytes.slice(0, mid));
      controller.enqueue(bytes.slice(mid));
      controller.close();
    },
  });
  return new Response(stream, { status: 200, headers: { "content-type": "text/event-stream" } });
}
