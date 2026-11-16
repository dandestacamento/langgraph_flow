import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "../api/client";
import { useChat } from "./useChat";

vi.mock("../api/client");

const mockedSendChatMessage = vi.mocked(client.sendChatMessage);
const mockedStreamChatMessage = vi.mocked(client.streamChatMessage);

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
});
