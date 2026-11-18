import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Composer } from "./Composer";

describe("Composer", () => {
  it("sends on Enter and clears the input", () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} disabled={false} />);

    const input = screen.getByRole("textbox", { name: "Type your message" });
    fireEvent.change(input, { target: { value: "What does E21 mean?" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onSend).toHaveBeenCalledWith("What does E21 mean?", []);
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

  it("uploads a picked file, shows a pill, and sends its metadata", async () => {
    const onSend = vi.fn();
    const onUpload = vi.fn().mockResolvedValue({
      attachment_id: "att-1",
      filename: "error.png",
      media_type: "image/png",
      size_bytes: 10,
    });
    render(<Composer onSend={onSend} disabled={false} onUpload={onUpload} />);

    const file = new File(["fake"], "error.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("Attach files"), { target: { files: [file] } });

    expect(await screen.findByText("error.png")).toBeInTheDocument();
    await waitFor(() => expect(onUpload).toHaveBeenCalled());

    const input = screen.getByRole("textbox", { name: "Type your message" });
    fireEvent.change(input, { target: { value: "What does this error mean?" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeEnabled());
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onSend).toHaveBeenCalledWith("What does this error mean?", [
      expect.objectContaining({ attachment_id: "att-1" }),
    ]);
    // Pills are cleared after sending.
    expect(screen.queryByText("error.png")).not.toBeInTheDocument();
  });

  it("attaches a pasted screenshot from the clipboard", async () => {
    const onUpload = vi.fn().mockResolvedValue({
      attachment_id: "att-2",
      filename: "pasted-image.png",
      media_type: "image/png",
      size_bytes: 10,
    });
    render(<Composer onSend={() => {}} disabled={false} onUpload={onUpload} />);

    const file = new File(["fake"], "pasted-image.png", { type: "image/png" });
    fireEvent.paste(screen.getByRole("textbox", { name: "Type your message" }), {
      clipboardData: { files: [file] },
    });

    expect(await screen.findByText("pasted-image.png")).toBeInTheDocument();
    await waitFor(() => expect(onUpload).toHaveBeenCalled());
  });

  it("surfaces an upload failure on the pill and blocks sending it", async () => {
    const onSend = vi.fn();
    const onUpload = vi.fn().mockRejectedValue(new Error("Unsupported file type."));
    render(<Composer onSend={onSend} disabled={false} onUpload={onUpload} />);

    const file = new File(["fake"], "notes.txt", { type: "text/plain" });
    fireEvent.change(screen.getByLabelText("Attach files"), { target: { files: [file] } });

    expect(await screen.findByText("Unsupported file type.")).toBeInTheDocument();
    // The failed attachment is not sendable - removing it is.
    fireEvent.click(screen.getByRole("button", { name: "Remove attachment notes.txt" }));
    expect(screen.queryByText("notes.txt")).not.toBeInTheDocument();
  });

  it("allows sending attachments with an empty message", async () => {
    const onSend = vi.fn();
    const onUpload = vi.fn().mockResolvedValue({
      attachment_id: "att-3",
      filename: "photo.png",
      media_type: "image/png",
      size_bytes: 10,
    });
    render(<Composer onSend={onSend} disabled={false} onUpload={onUpload} />);

    const file = new File(["fake"], "photo.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("Attach files"), { target: { files: [file] } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeEnabled());

    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(onSend).toHaveBeenCalledWith("", [expect.objectContaining({ attachment_id: "att-3" })]);
  });
});
