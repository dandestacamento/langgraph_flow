import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "../api/client";
import { useChat } from "./useChat";

vi.mock("../api/client");

const mockedSendChatMessage = vi.mocked(client.sendChatMessage);
const mockedStreamChatMessage = vi.mocked(client.streamChatMessage);
const mockedListThreads = vi.mocked(client.listThreads);
const mockedFetchThreadHistory = vi.mocked(client.fetchThreadHistory);

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
      onEvent({ type: "status", node: "condense" });
      onEvent({ type: "status", node: "rag_retriever" });
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
      { user_message: "What does E21 mean?", final_answer: "E21 is a drainage fault." },
      { user_message: "How do I fix it?", final_answer: "Clean the pump filter." },
    ]);

    const { result } = renderHook(() => useChat());
    await waitFor(() => expect(result.current.messages).toHaveLength(4));
    expect(result.current.messages[0]).toMatchObject({ role: "user", content: "What does E21 mean?" });
    expect(result.current.messages[3]).toMatchObject({
      role: "assistant",
      content: "Clean the pump filter.",
    });
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
});
