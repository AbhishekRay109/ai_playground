import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";
import { response, sseResponse, step } from "./test/fixtures";

function mockBackend(stream: () => Response) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith("/chat/stream")) return stream();
    if (url.endsWith("/health"))
      return Response.json({
        status: "degraded",
        version: "0.1.0",
        services: { llm: { ok: false, detail: "Ollama is not reachable", hint: "ollama serve" } },
      });
    if (url.endsWith("/sessions")) return Response.json([]);
    if (url.endsWith("/documents")) return Response.json([]);
    return Response.json({});
  });
}

afterEach(() => vi.restoreAllMocks());

test("streams an agent answer and shows the execution trace", async () => {
  const user = userEvent.setup();
  const final = response();
  mockBackend(() =>
    sseResponse([
      { type: "session", session_id: "sess-1", message_id: "msg-1" },
      { type: "tool_start", step: step({ status: "running", latency_ms: null }) },
      { type: "tool_end", step: step() },
      { type: "delta", text: "129 × 347 = " },
      { type: "done", response: final },
    ]),
  );
  render(<App />);
  await user.click(screen.getByRole("radio", { name: /Agent Mode/ }));
  await user.type(screen.getByLabelText("Question"), "What is 129 * 347?{Enter}");
  await waitFor(() => expect(screen.getByText("44763")).toBeInTheDocument());
  expect(screen.getByText("What is 129 * 347?")).toBeInTheDocument();
  expect(screen.getByText("ran: Calculator")).toBeInTheDocument();
  // Open the trace panel for this answer.
  await user.click(screen.getByRole("button", { name: "Show execution details" }));
  expect(screen.getByRole("complementary", { name: "Execution details" })).toHaveTextContent("129 * 347 = 44763");
});

test("shows a helpful error when the model is unavailable", async () => {
  const user = userEvent.setup();
  mockBackend(() =>
    sseResponse([
      { type: "session", session_id: "sess-1", message_id: "msg-1" },
      {
        type: "error",
        error: { code: "llm_unavailable", message: "Ollama is not reachable at http://localhost:11434.", hint: "Start Ollama" },
      },
    ]),
  );
  render(<App />);
  await user.click(screen.getByRole("radio", { name: /Direct LLM/ }));
  await user.type(screen.getByLabelText("Question"), "hi{Enter}");
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("Ollama is not reachable");
  expect(alert).toHaveTextContent("Start Ollama");
  expect(screen.getAllByRole("button", { name: /Retry/ }).length).toBeGreaterThan(0);
});
