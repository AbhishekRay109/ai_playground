import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { UiMessage } from "../../hooks/useChat";
import { response, step } from "../../test/fixtures";
import { MessageBubble } from "./MessageBubble";

const base: UiMessage = {
  id: "a1",
  role: "assistant",
  content: "",
  mode: "document_rag",
  status: "streaming",
  steps: [],
  sources: [],
};

test("shows a loading indicator and status while streaming", () => {
  render(<MessageBubble message={{ ...base, statusText: "Find relevant passages" }} />);
  expect(screen.getByRole("status", { name: "Working" })).toBeInTheDocument();
  expect(screen.getByText("Find relevant passages")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Copy answer" })).not.toBeInTheDocument();
});

test("error state shows the message, hint and a retry action", async () => {
  const user = userEvent.setup();
  const onRetry = vi.fn();
  render(
    <MessageBubble
      message={{
        ...base,
        status: "error",
        error: { code: "llm_unavailable", message: "Ollama is not reachable.", hint: "Run ollama serve" },
        request: { question: "q", mode: "direct", enabledTools: [] },
      }}
      onRetry={onRetry}
    />,
  );
  expect(screen.getByRole("alert")).toHaveTextContent("Ollama is not reachable.");
  expect(screen.getByText("Run ollama serve")).toBeInTheDocument();
  await user.click(screen.getAllByRole("button", { name: /Retry/ })[0]);
  expect(onRetry).toHaveBeenCalled();
});

test("renders markdown and only shows tools that actually ran", () => {
  const r = response({ executed_tools: ["calculator"], available_tools: ["web_search", "calculator"] });
  render(<MessageBubble message={{ ...base, mode: "agent", status: "done", content: r.answer, response: r, steps: [step()] }} />);
  expect(screen.getByText("44763").tagName).toBe("STRONG");
  expect(screen.getByText("ran: Calculator")).toBeInTheDocument();
  expect(screen.queryByText("ran: Web search")).not.toBeInTheDocument();
});
