import { useCallback, useEffect, useRef, useState } from "react";

import { sendChatMessage, streamChatMessage } from "../api/client";
import type { RoutingSummary } from "../api/client";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  /** Populated only on assistant messages, while the answer is still
   * streaming in (last node completed so far, e.g. "rag_retriever"). */
  statusNode?: string;
  /** Populated once the turn completes - the routing/retrieval/tool
   * trace behind this answer, rendered by RoutingDetails. */
  routingSummary?: RoutingSummary;
}

const THREAD_ID_STORAGE_KEY = "routing-lab3-chat-thread-id";

function getOrCreateThreadId(): string {
  const existing = localStorage.getItem(THREAD_ID_STORAGE_KEY);
  if (existing) return existing;
  const generated = crypto.randomUUID();
  localStorage.setItem(THREAD_ID_STORAGE_KEY, generated);
  return generated;
}

/** A `TypeError` is what `fetch` itself throws for a connectivity failure
 * (DNS/refused/offline) - distinct from an HTTP error response, which
 * `sendChatMessage`/`streamChatMessage` instead reject with a regular
 * `Error` carrying the status code. Worth telling these apart in the UI:
 * one means "check your connection," the other means "the server/answer
 * itself failed." */
function describeError(err: unknown): string {
  if (err instanceof TypeError) {
    return "Network error - check your connection and try again.";
  }
  return err instanceof Error ? err.message : "Something went wrong.";
}

/**
 * Owns the conversation's `thread_id` (persisted in localStorage, so a
 * page refresh resumes the same backend-side conversation_history - the
 * browser-level analogue of smarthome-csr's `st.session_state` pattern)
 * and the message list, and wraps the streaming/non-streaming API calls
 * in app/api/client.ts.
 */
export function useChat() {
  const [threadId] = useState(getOrCreateThreadId);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  // The most recent message that failed to send, kept only so "Retry"
  // can resend the exact same text - cleared on any successful send.
  const lastFailedMessageRef = useRef<string | null>(null);

  useEffect(() => {
    return () => abortControllerRef.current?.abort();
  }, []);

  const sendMessage = useCallback(
    async (text: string, useStreaming = true) => {
      const trimmed = text.trim();
      if (!trimmed || isSending) return;

      setError(null);
      setIsSending(true);
      const userMessage: ChatMessage = { id: crypto.randomUUID(), role: "user", content: trimmed };
      const assistantMessageId = crypto.randomUUID();
      setMessages((prev) => [
        ...prev,
        userMessage,
        { id: assistantMessageId, role: "assistant", content: "" },
      ]);

      try {
        if (useStreaming) {
          const controller = new AbortController();
          abortControllerRef.current = controller;
          await streamChatMessage(
            threadId,
            trimmed,
            (event) => {
              if (event.type === "status") {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMessageId ? { ...m, statusNode: event.node } : m,
                  ),
                );
              } else {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMessageId
                      ? {
                          ...m,
                          content: event.final_answer,
                          statusNode: undefined,
                          routingSummary: event.routing_summary,
                        }
                      : m,
                  ),
                );
              }
            },
            controller.signal,
          );
        } else {
          const response = await sendChatMessage(threadId, trimmed);
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMessageId
                ? { ...m, content: response.final_answer, routingSummary: response.routing_summary }
                : m,
            ),
          );
        }
        lastFailedMessageRef.current = null;
      } catch (err) {
        lastFailedMessageRef.current = trimmed;
        setError(describeError(err));
        setMessages((prev) => prev.filter((m) => m.id !== assistantMessageId));
      } finally {
        setIsSending(false);
      }
    },
    [threadId, isSending],
  );

  const retryLastMessage = useCallback(() => {
    if (lastFailedMessageRef.current) {
      void sendMessage(lastFailedMessageRef.current);
    }
  }, [sendMessage]);

  return { threadId, messages, isSending, error, sendMessage, retryLastMessage };
}
