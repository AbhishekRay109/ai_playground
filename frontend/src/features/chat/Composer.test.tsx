import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Composer } from "./Composer";

test("send is disabled until there is text and Enter submits", async () => {
  const user = userEvent.setup();
  const onSend = vi.fn();
  render(<Composer mode="direct" enabledTools={[]} busy={false} onSend={onSend} onStop={() => {}} />);
  expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  await user.type(screen.getByLabelText("Question"), "Hello there{Enter}");
  expect(onSend).toHaveBeenCalledWith("Hello there");
  expect(screen.getByLabelText("Question")).toHaveValue("");
});

test("while busy the stop action replaces send", async () => {
  const user = userEvent.setup();
  const onStop = vi.fn();
  render(<Composer mode="agent" enabledTools={[]} busy onSend={() => {}} onStop={onStop} />);
  expect(screen.queryByRole("button", { name: "Send" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Stop generating" }));
  expect(onStop).toHaveBeenCalled();
  expect(screen.getByText("No tools enabled")).toBeInTheDocument();
});
