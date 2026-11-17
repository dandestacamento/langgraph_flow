import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Composer } from "./Composer";

describe("Composer", () => {
  it("sends on Enter and clears the input", () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} disabled={false} />);

    const input = screen.getByRole("textbox", { name: "Type your message" });
    fireEvent.change(input, { target: { value: "What does E21 mean?" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onSend).toHaveBeenCalledWith("What does E21 mean?");
    expect(input).toHaveValue("");
  });

  it("does not send on Shift+Enter (newline instead)", () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} disabled={false} />);

    const input = screen.getByRole("textbox", { name: "Type your message" });
    fireEvent.change(input, { target: { value: "line one" } });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });

    expect(onSend).not.toHaveBeenCalled();
    expect(input).toHaveValue("line one");
  });

  it("ignores Enter while disabled or empty", () => {
    const onSend = vi.fn();
    const { rerender } = render(<Composer onSend={onSend} disabled={false} />);

    const input = screen.getByRole("textbox", { name: "Type your message" });
    fireEvent.keyDown(input, { key: "Enter" }); // empty
    expect(onSend).not.toHaveBeenCalled();

    rerender(<Composer onSend={onSend} disabled={true} />);
    fireEvent.change(input, { target: { value: "hello" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();
  });

  it("replaces Send with a Stop button while a send is in flight", () => {
    const onStop = vi.fn();
    const { rerender } = render(<Composer onSend={() => {}} disabled={false} onStop={onStop} />);
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Stop" })).not.toBeInTheDocument();

    rerender(<Composer onSend={() => {}} disabled={true} onStop={onStop} />);
    const stop = screen.getByRole("button", { name: "Stop" });
    fireEvent.click(stop);
    expect(onStop).toHaveBeenCalled();
  });
});
