import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "../api/client";
import { useChat } from "./useChat";

vi.mock("../api/client");

const mockedSendChatMessage = vi.mocked(client.sendChatMessage);
const mockedStreamChatMessage = vi.mocked(client.streamChatMessage);
const mockedListThreads = vi.mocked(client.listThreads);
const mockedFetchThreadHistory = vi.mocked(client.fetchThreadHistory);
const mockedRenameThread = vi.mocked(client.renameThread);
const mockedDeleteThread = vi.mocked(client.deleteThread);
const mockedRestoreThread = vi.mocked(client.restoreThread);

const EMPTY_SUMMARY: client.RoutingSummary = {
  topics: [],
  subtopics: {},
  chapters: {},
  passages: {},
  tool_results: {},
  is_multi_hop: false,
  hop_results: [],
  recovery_attempts: {},
};

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  // Mount-time defaults: an empty conversation list and no past turns.
  mockedListThreads.mockResolvedValue([]);
  mockedFetchThreadHistory.mockResolvedValue([]);
});

describe("useChat", () => {
  it("appends a user message and the final answer for a non-streaming send", async () => {
    mockedSendChatMessage.mockResolvedValue({
      thread_id: "t1",
      self_contained_question: "What does E21 mean?",
      final_answer: "E21 is a drainage fault.",
      routing_summary: EMPTY_SUMMARY,
    });

    const { result } = renderHook(() => useChat());
    await act(async () => {
      await result.current.sendMessage("What does E21 mean?", false);
    });

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0]).toMatchObject({ role: "user", content: "What does E21 mean?" });
    expect(result.current.messages[1]).toMatchObject({
      role: "assistant",
      content: "E21 is a drainage fault.",
    });
    expect(result.current.error).toBeNull();
  });

  it("applies streaming status events then the final answer event", async () => {
    mockedStreamChatMessage.mockImplementation(async (_threadId, _message, onEvent) => {
      onEvent({ type: "status", node: "condense", elapsedMs: 800 });
      onEvent({ type: "status", node: "invoke_routing_pipeline", elapsedMs: 2400 });
      onEvent({
        type: "answer",
        final_answer: "E21 is a drainage fault.",
        routing_summary: { ...EMPTY_SUMMARY, topics: ["appliances"] },
      });
    });

    const { result } = renderHook(() => useChat());
    await act(async () => {
      await result.current.sendMessage("What does E21 mean?");
    });

    const assistantMessage = result.current.messages[1];
    expect(assistantMessage.content).toBe("E21 is a drainage fault.");
    expect(assistantMessage.statusNode).toBeUndefined();
    expect(assistantMessage.routingSummary?.topics).toEqual(["appliances"]);
    // The node-by-node timeline is preserved for the inspector
    // (chat-ui-plan3.md §2.2).
    expect(assistantMessage.executionTrace).toEqual([
      { node: "condense", elapsedMs: 800 },
      { node: "invoke_routing_pipeline", elapsedMs: 2400 },
    ]);
  });

  it("surfaces a friendly message for a network failure and removes the pending assistant bubble", async () => {
    mockedStreamChatMessage.mockRejectedValue(new TypeError("Failed to fetch"));

    const { result } = renderHook(() => useChat());
    await act(async () => {
      await result.current.sendMessage("What does E21 mean?");
    });

    expect(result.current.error).toBe("Network error - check your connection and try again.");
    expect(result.current.messages).toHaveLength(1); // only the user message remains
  });

  it("surfaces a backend error's own message as-is", async () => {
    mockedStreamChatMessage.mockRejectedValue(new Error("Chat stream request failed: 502 Bad Gateway"));

    const { result } = renderHook(() => useChat());
    await act(async () => {
      await result.current.sendMessage("What does E21 mean?");
    });

    expect(result.current.error).toBe("Chat stream request failed: 502 Bad Gateway");
  });

  it("retryLastMessage resends the exact text that failed", async () => {
    mockedStreamChatMessage.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    const { result } = renderHook(() => useChat());
    await act(async () => {
      await result.current.sendMessage("What does E21 mean?");
    });
    expect(result.current.error).not.toBeNull();

    mockedStreamChatMessage.mockImplementationOnce(async (_threadId, _message, onEvent) => {
      onEvent({ type: "answer", final_answer: "E21 is a drainage fault.", routing_summary: EMPTY_SUMMARY });
    });
    await act(async () => {
      result.current.retryLastMessage();
    });

    await waitFor(() => expect(result.current.error).toBeNull());
    expect(mockedStreamChatMessage).toHaveBeenLastCalledWith(
      expect.any(String),
      "What does E21 mean?",
      expect.any(Function),
      expect.anything(),
    );
  });

  it("persists the same thread_id across remounts via localStorage", () => {
    const { result: first } = renderHook(() => useChat());
    const { result: second } = renderHook(() => useChat());
    expect(second.current.threadId).toBe(first.current.threadId);
  });

  it("restores the active conversation's past turns on mount", async () => {
    mockedFetchThreadHistory.mockResolvedValue([
      {
        user_message: "What does E21 mean?",
        final_answer: "E21 is a drainage fault.",
        routing_summary: {
          ...EMPTY_SUMMARY,
          topics: ["appliances"],
          passages: {
            appliances: [
              { chapter_id: "chapter_03_faults", document_id: "d1", subtopic: null, score: 0.79, text: "E21…" },
            ],
          },
        },
      },
      // A turn recorded before per-turn summaries existed: {}
      { user_message: "How do I fix it?", final_answer: "Clean the pump filter.", routing_summary: {} },
    ]);

    const { result } = renderHook(() => useChat());
    await waitFor(() => expect(result.current.messages).toHaveLength(4));
    expect(result.current.messages[0]).toMatchObject({ role: "user", content: "What does E21 mean?" });
    // Restored citations survive the reload...
    expect(result.current.messages[1].routingSummary?.topics).toEqual(["appliances"]);
    // ...and a pre-summary turn degrades to a plain message.
    expect(result.current.messages[3]).toMatchObject({
      role: "assistant",
      content: "Clean the pump filter.",
    });
    expect(result.current.messages[3].routingSummary).toBeUndefined();
    expect(result.current.isLoadingHistory).toBe(false);
  });

  it("newConversation switches to a fresh thread_id and clears the messages", async () => {
    mockedFetchThreadHistory.mockResolvedValueOnce([
      { user_message: "Old question", final_answer: "Old answer" },
    ]);

    const { result } = renderHook(() => useChat());
    await waitFor(() => expect(result.current.messages).toHaveLength(2));
    const originalThreadId = result.current.threadId;

    act(() => {
      result.current.newConversation();
    });

    expect(result.current.threadId).not.toBe(originalThreadId);
    expect(localStorage.getItem("routing-lab3-chat-thread-id")).toBe(result.current.threadId);
    await waitFor(() => expect(result.current.messages).toHaveLength(0));
  });

  it("switchConversation loads the selected thread's history", async () => {
    mockedFetchThreadHistory.mockImplementation(async (threadId) =>
      threadId === "thread-b"
        ? [{ user_message: "Fridge too warm", final_answer: "Check the thermostat." }]
        : [],
    );

    const { result } = renderHook(() => useChat());
    act(() => {
      result.current.switchConversation("thread-b");
    });

    expect(result.current.threadId).toBe("thread-b");
    expect(localStorage.getItem("routing-lab3-chat-thread-id")).toBe("thread-b");
    await waitFor(() => expect(result.current.messages).toHaveLength(2));
    expect(result.current.messages[1]).toMatchObject({
      role: "assistant",
      content: "Check the thermostat.",
    });
  });

  it("surfaces a failed history restore as an error that Retry can re-run", async () => {
    mockedFetchThreadHistory.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    const { result } = renderHook(() => useChat());
    await waitFor(() =>
      expect(result.current.error).toBe(
        "Couldn't load this conversation's history - check your connection and try again.",
      ),
    );
    expect(result.current.isLoadingHistory).toBe(false);

    mockedFetchThreadHistory.mockResolvedValueOnce([
      { user_message: "What does E21 mean?", final_answer: "E21 is a drainage fault." },
    ]);
    act(() => {
      result.current.retryLastMessage();
    });

    await waitFor(() => expect(result.current.messages).toHaveLength(2));
    expect(result.current.error).toBeNull();
    expect(result.current.isLoadingHistory).toBe(false);
  });

  it("refreshes the conversation list after a successful send", async () => {
    mockedStreamChatMessage.mockImplementation(async (_threadId, _message, onEvent) => {
      onEvent({ type: "answer", final_answer: "Done.", routing_summary: EMPTY_SUMMARY });
    });
    mockedListThreads
      .mockResolvedValueOnce([]) // the mount-time load
      .mockResolvedValue([
        { thread_id: "t1", title: "What does E21 mean?", updated_at: "2026-01-01T00:00:00Z" },
      ]);

    const { result } = renderHook(() => useChat());
    await act(async () => {
      await result.current.sendMessage("What does E21 mean?");
    });

    await waitFor(() => expect(result.current.threads).toHaveLength(1));
    expect(result.current.threads[0].title).toBe("What does E21 mean?");
    expect(mockedListThreads).toHaveBeenCalledTimes(2);
  });

  it("regenerateLastTurn re-asks the most recent user message", async () => {
    mockedStreamChatMessage.mockImplementation(async (_threadId, _message, onEvent) => {
      onEvent({ type: "answer", final_answer: "First answer.", routing_summary: EMPTY_SUMMARY });
    });

    const { result } = renderHook(() => useChat());
    await act(async () => {
      await result.current.sendMessage("What does E21 mean?");
    });

    await act(async () => {
      result.current.regenerateLastTurn();
    });

    await waitFor(() => expect(mockedStreamChatMessage).toHaveBeenCalledTimes(2));
    expect(mockedStreamChatMessage).toHaveBeenLastCalledWith(
      expect.any(String),
      "What does E21 mean?",
      expect.any(Function),
      expect.anything(),
    );
  });

  it("renameConversation renames via the API and refreshes the list", async () => {
    mockedRenameThread.mockResolvedValue(undefined);

    const { result } = renderHook(() => useChat());
    await act(async () => {
      await result.current.renameConversation("thread-1", "  Warm fridge fix  ");
    });

    expect(mockedRenameThread).toHaveBeenCalledWith("thread-1", "Warm fridge fix");
    expect(mockedListThreads).toHaveBeenCalledTimes(2); // mount + after rename
    expect(result.current.error).toBeNull();
  });

  it("deleteConversation of the active thread starts a fresh conversation", async () => {
    mockedDeleteThread.mockResolvedValue(undefined);
    mockedFetchThreadHistory.mockResolvedValue([
      { user_message: "Old question", final_answer: "Old answer" },
    ]);

    const { result } = renderHook(() => useChat());
    await waitFor(() => expect(result.current.messages).toHaveLength(2));
    const originalThreadId = result.current.threadId;

    mockedFetchThreadHistory.mockResolvedValue([]);
    await act(async () => {
      await result.current.deleteConversation(originalThreadId);
    });

    expect(mockedDeleteThread).toHaveBeenCalledWith(originalThreadId);
    expect(result.current.threadId).not.toBe(originalThreadId);
    await waitFor(() => expect(result.current.messages).toHaveLength(0));
  });

  it("deleteConversation of a non-active thread leaves the current conversation alone", async () => {
    mockedDeleteThread.mockResolvedValue(undefined);

    const { result } = renderHook(() => useChat());
    const originalThreadId = result.current.threadId;

    await act(async () => {
      await result.current.deleteConversation("some-other-thread");
    });

    expect(mockedDeleteThread).toHaveBeenCalledWith("some-other-thread");
    expect(result.current.threadId).toBe(originalThreadId);
  });

  it("offers Undo after a delete, and undoDelete restores the conversation", async () => {
    mockedDeleteThread.mockResolvedValue(undefined);
    mockedRestoreThread.mockResolvedValue(undefined);
    mockedListThreads.mockResolvedValue([
      { thread_id: "thread-1", title: "Fridge E05", updated_at: "2026-01-01T00:00:00Z" },
    ]);

    const { result } = renderHook(() => useChat());
    await waitFor(() => expect(result.current.threads).toHaveLength(1));

    await act(async () => {
      await result.current.deleteConversation("thread-1");
    });
    expect(result.current.recentlyDeleted).toEqual({ threadId: "thread-1", title: "Fridge E05" });

    await act(async () => {
      await result.current.undoDelete();
    });
    expect(mockedRestoreThread).toHaveBeenCalledWith("thread-1");
    expect(result.current.recentlyDeleted).toBeNull();
  });

  it("stopStreaming marks the in-flight turn stopped instead of erroring", async () => {
    mockedStreamChatMessage.mockImplementation(
      (_threadId, _message, _onEvent, signal) =>
        new Promise((_resolve, reject) => {
          signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
        }),
    );

    const { result } = renderHook(() => useChat());
    let sendPromise: Promise<void>;
    act(() => {
      sendPromise = result.current.sendMessage("What does E21 mean?");
    });
    await waitFor(() => expect(result.current.isSending).toBe(true));

    act(() => {
      result.current.stopStreaming();
    });
    await act(async () => {
      await sendPromise;
    });

    expect(result.current.isSending).toBe(false);
    expect(result.current.error).toBeNull();
    const assistantMessage = result.current.messages[1];
    expect(assistantMessage).toMatchObject({ role: "assistant", stopped: true, content: "" });
  });
});
