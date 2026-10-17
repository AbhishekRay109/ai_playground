import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import type { Mode, ToolName } from "../../types/api";
import { ChatView } from "./ChatView";
import { ModeSelector } from "./ModeSelector";

function Harness() {
  const [mode, setMode] = useState<Mode>("document_rag");
  const [tools, setTools] = useState<ToolName[]>(["calculator"]);
  return (
    <ChatView
      messages={[]}
      busy={false}
      mode={mode}
      onModeChange={setMode}
      enabledTools={tools}
      onToolsChange={setTools}
      onSend={() => {}}
      onStop={() => {}}
      onRetry={() => {}}
      onFeedback={() => {}}
      onInspect={() => {}}
      onClear={() => {}}
      onTogglePanel={() => {}}
    />
  );
}

test("exactly one execution mode is selected at a time", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  const { rerender } = render(<ModeSelector value="document_rag" onChange={onChange} />);
  const radios = screen.getAllByRole("radio");
  expect(radios).toHaveLength(5);
  expect(radios.filter((r) => r.getAttribute("aria-checked") === "true")).toHaveLength(1);
  await user.click(screen.getByRole("radio", { name: /SQL Assistant/ }));
  expect(onChange).toHaveBeenCalledWith("sql");
  rerender(<ModeSelector value="sql" onChange={onChange} />);
  expect(screen.getByRole("radio", { name: /SQL Assistant/ })).toHaveAttribute("aria-checked", "true");
  expect(screen.getByRole("radio", { name: /Document RAG/ })).toHaveAttribute("aria-checked", "false");
});

test("tool toggles appear only in Agent Mode and update availability", async () => {
  const user = userEvent.setup();
  render(<Harness />);
  expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  await user.click(screen.getByRole("radio", { name: /Agent Mode/ }));
  const web = screen.getByRole("switch", { name: /Web search/ });
  expect(web).toHaveAttribute("aria-checked", "false");
  expect(screen.getByRole("switch", { name: /Calculator/ })).toHaveAttribute("aria-checked", "true");
  await user.click(web);
  expect(web).toHaveAttribute("aria-checked", "true");
  // The composer reflects the selected mode and the tools *available* to the agent.
  const indicator = screen.getByTestId("mode-indicator");
  expect(indicator).toHaveTextContent("Mode: Agent Mode");
  expect(indicator).toHaveTextContent("Web search");
});

test("example questions are shown for the selected mode", async () => {
  const user = userEvent.setup();
  render(<Harness />);
  expect(screen.getByText("What does my uploaded policy say about exclusions?")).toBeInTheDocument();
  await user.click(screen.getByRole("radio", { name: /SQL Assistant/ }));
  expect(screen.getByText("What was our highest-selling product by units?")).toBeInTheDocument();
});
