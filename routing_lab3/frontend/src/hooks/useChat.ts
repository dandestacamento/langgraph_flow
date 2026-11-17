import { useCallback, useEffect, useRef, useState } from "react";

import { fetchThreadHistory, listThreads, sendChatMessage, streamChatMessage } from "../api/client";
import type { RoutingSummary, ThreadSummary } from "../api/client";

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
  /** Set when app/chat/guardrails.py blocked this turn's input
   * ("prompt_injection") or rewrote its output ("secret_leakage") -
   * null/undefined otherwise. Rendered as a small badge, not hidden,
   * so a blocked/redacted answer isn't mistaken for a normal one. */
  guardrailBlockedReason?: string | null;
}

const THREAD_ID_STORAGE_KEY = "routing-lab3-chat-thread-id";

function getOrCreateThreadId(): string {
  const existing = localStorage.getItem(THREAD_ID_STORAGE_KEY);
  if (existing) return existing;
  const generated = crypto.randomUUID();
  localStorage.setItem(THREAD_ID_STORAGE_KEY, generated);
  return generated;
}

function newThreadId(): string {
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
 *
 * Phase E (chat-ui-plan1.md): also owns the user's conversation *list*
 * (`threads`, refreshed after every successful send), restores a
 * conversation's past turns when it becomes active (on first load and
 * on `switchConversation`), and supports starting a fresh one
 * (`newConversation`).
 */
export function useChat() {
  const [threadId, setThreadId] = useState(getOrCreateThreadId);
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isSending, setIsSending] = useState(false);
  // Starts true: the mount-time history restore below is already in
  // flight by first render. Set back to true from the switch/new event
  // handlers (not inside the effect) when the active thread changes.
  const [isLoadingHistory, setIsLoadingHistory] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Bumped by retryLastMessage to re-run the history-restore effect
  // after a failed load (e.g. the backend was unreachable).
  const [historyReloadNonce, setHistoryReloadNonce] = useState(0);
  const abortControllerRef = useRef<AbortController | null>(null);
  // The most recent message that failed to send, kept only so "Retry"
  // can resend the exact same text - cleared on any successful send.
  const lastFailedMessageRef = useRef<string | null>(null);
  // Monotonic guard: a history load only applies if nothing (a thread
  // switch, a send) superseded it while its fetch was in flight.
  const historyLoadSeqRef = useRef(0);

  useEffect(() => {
    return () => abortControllerRef.current?.abort();
  }, []);

  // Non-fatal by design: the chat itself works without the sidebar's
  // list, so a failure here degrades to an empty list, not an error
  // banner blocking the composer.
  const refreshThreads = useCallback(() => {
    listThreads()
      .then(setThreads)
      .catch(() => {
        // Degrade gracefully - see above.
      });
  }, []);

  useEffect(() => {
    refreshThreads();
  }, [refreshThreads]);

  // Restore the active conversation's past turns whenever it changes
  // (including the initial mount - before this, a page refresh kept the
  // backend-side history but showed an empty window).
  useEffect(() => {
    const seq = ++historyLoadSeqRef.current;
    fetchThreadHistory(threadId)
      .then((turns) => {
        if (seq !== historyLoadSeqRef.current) return;
        setMessages(
          turns.flatMap((turn): ChatMessage[] => [
            { id: crypto.randomUUID(), role: "user", content: turn.user_message },
            { id: crypto.randomUUID(), role: "assistant", content: turn.final_answer },
          ]),
        );
      })
      .catch(() => {
        // A failed restore must be *visible*, not a silently blank
        // window a user can mistake for a deleted conversation - the
        // error banner's Retry re-runs this load (see retryLastMessage).
        if (seq !== historyLoadSeqRef.current) return;
        setError("Couldn't load this conversation's history - check your connection and try again.");
      })
      .finally(() => {
        if (seq === historyLoadSeqRef.current) setIsLoadingHistory(false);
      });
  }, [threadId, historyReloadNonce]);

  const sendMessage = useCallback(
    async (text: string, useStreaming = true) => {
      const trimmed = text.trim();
      if (!trimmed || isSending) return;

      // A send supersedes any still-in-flight history load - without
      // this, a slow restore could resolve late and wipe the new turn.
      historyLoadSeqRef.current += 1;
      setIsLoadingHistory(false);
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
                          guardrailBlockedReason: event.guardrail_blocked_reason,
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
                ? {
                    ...m,
                    content: response.final_answer,
                    routingSummary: response.routing_summary,
                    guardrailBlockedReason: response.guardrail_blocked_reason,
                  }
                : m,
            ),
          );
        }
        lastFailedMessageRef.current = null;
        // A successful turn changes this thread's title (if new) and
        // recency ordering - refresh the list to reflect it.
        refreshThreads();
      } catch (err) {
        lastFailedMessageRef.current = trimmed;
        setError(describeError(err));
        setMessages((prev) => prev.filter((m) => m.id !== assistantMessageId));
      } finally {
        setIsSending(false);
      }
    },
    [threadId, isSending, refreshThreads],
  );

  const retryLastMessage = useCallback(() => {
    if (lastFailedMessageRef.current) {
      void sendMessage(lastFailedMessageRef.current);
      return;
    }
    // No failed *send* to retry - the error banner is up because a
    // history restore failed, so Retry re-runs that load instead.
    setError(null);
    setIsLoadingHistory(true);
    setHistoryReloadNonce((nonce) => nonce + 1);
  }, [sendMessage]);

  const newConversation = useCallback(() => {
    if (isSending) return;
    historyLoadSeqRef.current += 1; // discard any in-flight restore
    setThreadId(newThreadId());
    setIsLoadingHistory(true);
    setMessages([]);
    setError(null);
    lastFailedMessageRef.current = null;
  }, [isSending]);

  const switchConversation = useCallback(
    (nextThreadId: string) => {
      if (isSending || nextThreadId === threadId) return;
      localStorage.setItem(THREAD_ID_STORAGE_KEY, nextThreadId);
      setThreadId(nextThreadId); // history restores via the effect above
      setIsLoadingHistory(true);
      setMessages([]);
      setError(null);
      lastFailedMessageRef.current = null;
    },
    [isSending, threadId],
  );

  return {
    threadId,
    threads,
    messages,
    isSending,
    isLoadingHistory,
    error,
    sendMessage,
    retryLastMessage,
    newConversation,
    switchConversation,
  };
}
