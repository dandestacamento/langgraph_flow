import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ThreadSummary } from "../api/client";
import { ConversationSidebar } from "./ConversationSidebar";

const THREADS: ThreadSummary[] = [
  { thread_id: "thread-1", title: "What does E21 mean?", updated_at: "2026-01-01T00:00:00Z" },
  { thread_id: "thread-2", title: "Fridge is too warm", updated_at: "2026-01-02T00:00:00Z" },
];

const noop = () => {};

describe("ConversationSidebar", () => {
  it("lists every conversation and marks the active one", () => {
    render(
      <ConversationSidebar
        threads={THREADS}
        activeThreadId="thread-2"
        onSelect={noop}
        onNew={noop}
        onRename={noop}
        onDelete={noop}
      />,
    );

    expect(screen.getByText("What does E21 mean?")).toBeInTheDocument();
    const active = screen.getByRole("button", { name: /^Fridge is too warm/ });
    expect(active).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("button", { name: /^What does E21 mean/ })).not.toHaveAttribute(
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
        onRename={noop}
        onDelete={noop}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /^Fridge is too warm/ }));
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
        onNew={noop}
        onRename={noop}
        onDelete={noop}
      />,
    );

    const button = screen.getByRole("button", { name: /^Fridge is too warm/ });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("shows an empty state when there are no past conversations", () => {
    render(
      <ConversationSidebar
        threads={[]}
        activeThreadId="t"
        onSelect={noop}
        onNew={noop}
        onRename={noop}
        onDelete={noop}
      />,
    );
    expect(screen.getByText("No past conversations yet.")).toBeInTheDocument();
  });

  it("filters the list by the search query", () => {
    render(
      <ConversationSidebar
        threads={THREADS}
        activeThreadId="thread-1"
        onSelect={noop}
        onNew={noop}
        onRename={noop}
        onDelete={noop}
      />,
    );

    fireEvent.change(screen.getByRole("searchbox", { name: "Search conversations" }), {
      target: { value: "fridge" },
    });

    expect(screen.getByText("Fridge is too warm")).toBeInTheDocument();
    expect(screen.queryByText("What does E21 mean?")).not.toBeInTheDocument();

    fireEvent.change(screen.getByRole("searchbox", { name: "Search conversations" }), {
      target: { value: "no such conversation" },
    });
    expect(screen.getByText("No conversations match your search.")).toBeInTheDocument();
  });

  it("renames a conversation via the inline form (Enter saves, Escape cancels)", () => {
    const onRename = vi.fn();
    render(
      <ConversationSidebar
        threads={THREADS}
        activeThreadId="thread-1"
        onSelect={noop}
        onNew={noop}
        onRename={onRename}
        onDelete={noop}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Rename conversation: Fridge is too warm" }));
    const input = screen.getByRole("textbox", { name: "Conversation title" });
    fireEvent.change(input, { target: { value: "Warm fridge fix" } });
    fireEvent.submit(input);
    expect(onRename).toHaveBeenCalledWith("thread-2", "Warm fridge fix");

    // Escape cancels without renaming.
    fireEvent.click(screen.getByRole("button", { name: /Rename conversation: What does E21/ }));
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Conversation title" }), {
      key: "Escape",
    });
    expect(screen.queryByRole("textbox", { name: "Conversation title" })).not.toBeInTheDocument();
    expect(onRename).toHaveBeenCalledTimes(1);
  });

  it("deletes a conversation only after the two-step confirmation", () => {
    const onDelete = vi.fn();
    render(
      <ConversationSidebar
        threads={THREADS}
        activeThreadId="thread-1"
        onSelect={noop}
        onNew={noop}
        onRename={noop}
        onDelete={onDelete}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Delete conversation: Fridge is too warm" }));
    expect(onDelete).not.toHaveBeenCalled(); // first click only arms

    fireEvent.click(screen.getByRole("button", { name: "Confirm?" }));
    expect(onDelete).toHaveBeenCalledWith("thread-2");
  });
});
