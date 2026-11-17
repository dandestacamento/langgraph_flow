import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ThreadSummary } from "../api/client";
import { ConversationSidebar } from "./ConversationSidebar";

const THREADS: ThreadSummary[] = [
  { thread_id: "thread-1", title: "What does E21 mean?", updated_at: "2026-01-01T00:00:00Z" },
  { thread_id: "thread-2", title: "Fridge is too warm", updated_at: "2026-01-02T00:00:00Z" },
];

describe("ConversationSidebar", () => {
  it("lists every conversation and marks the active one", () => {
    render(
      <ConversationSidebar
        threads={THREADS}
        activeThreadId="thread-2"
        onSelect={() => {}}
        onNew={() => {}}
      />,
    );

    expect(screen.getByText("What does E21 mean?")).toBeInTheDocument();
    const active = screen.getByRole("button", { name: /Fridge is too warm/ });
    expect(active).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("button", { name: /What does E21 mean/ })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("invokes onSelect with the clicked thread's id and onNew for the new-conversation button", () => {
    const onSelect = vi.fn();
    const onNew = vi.fn();
    render(
      <ConversationSidebar
        threads={THREADS}
        activeThreadId="thread-1"
        onSelect={onSelect}
        onNew={onNew}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Fridge is too warm/ }));
    expect(onSelect).toHaveBeenCalledWith("thread-2");

    fireEvent.click(screen.getByRole("button", { name: "+ New conversation" }));
    expect(onNew).toHaveBeenCalled();
  });

  it("disables switching and creating while a send is in flight", () => {
    const onSelect = vi.fn();
    render(
      <ConversationSidebar
        threads={THREADS}
        activeThreadId="thread-1"
        disabled
        onSelect={onSelect}
        onNew={() => {}}
      />,
    );

    const button = screen.getByRole("button", { name: /Fridge is too warm/ });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("shows an empty state when there are no past conversations", () => {
    render(
      <ConversationSidebar threads={[]} activeThreadId="t" onSelect={() => {}} onNew={() => {}} />,
    );
    expect(screen.getByText("No past conversations yet.")).toBeInTheDocument();
  });
});
