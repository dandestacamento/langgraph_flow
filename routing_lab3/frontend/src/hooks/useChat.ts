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
      } catch (err) {
        setError(err instanceof Error ? err.message : "Something went wrong.");
        setMessages((prev) => prev.filter((m) => m.id !== assistantMessageId));
      } finally {
        setIsSending(false);
      }
    },
    [threadId, isSending],
  );

  return { threadId, messages, isSending, error, sendMessage };
}
