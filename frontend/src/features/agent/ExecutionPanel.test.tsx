import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { response, step } from "../../test/fixtures";
import { ExecutionPanel } from "./ExecutionPanel";

test("distinguishes available, requested and executed tools", () => {
  const r = response({
    available_tools: ["document_retrieval", "web_search", "calculator"],
    selected_tools: ["web_search", "calculator"],
    executed_tools: ["calculator"],
    steps: [
      step({ id: "r", name: "web_search", status: "rejected", result_summary: "not enabled", details: {} }),
      step(),
    ],
  });
  render(
    <ExecutionPanel
      availableTools={[]}
      message={{ id: "m", role: "assistant", content: r.answer, mode: "agent", status: "done", response: r, steps: r.steps, sources: [] }}
    />,
  );
  const executedRow = screen.getByText("Tools executed").closest("div")!;
  expect(within(executedRow).getByText("Calculator")).toBeInTheDocument();
  expect(within(executedRow).queryByText("Web search")).not.toBeInTheDocument();
  const availableRow = screen.getByText("Tools available").closest("div")!;
  expect(within(availableRow).getByText("Document retrieval")).toBeInTheDocument();
  expect(screen.getByText("rejected")).toBeInTheDocument();
  expect(screen.getByText("1234 ms")).toBeInTheDocument();
  expect(screen.getByText("llama3.2:3b")).toBeInTheDocument();
});

test("expands a step to show retrieved chunks", async () => {
  const user = userEvent.setup();
  const chunkStep = step({
    name: "document_retrieval",
    details: {
      top_k: 5,
      score_threshold: 0.3,
      candidates: 4,
      chunks: [{ chunk_id: "c1", filename: "policy.md", page: 3, chunk_index: 2, score: 0.81, text: "Book 21 days ahead." }],
    },
  });
  render(
    <ExecutionPanel
      availableTools={[]}
      message={{ id: "m", role: "assistant", content: "", mode: "document_rag", status: "streaming", steps: [chunkStep], sources: [] }}
    />,
  );
  await user.click(screen.getByRole("button", { expanded: false }));
  expect(screen.getByText("Book 21 days ahead.")).toBeInTheDocument();
  expect(screen.getByText("page 3")).toBeInTheDocument();
});
