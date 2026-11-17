import { useEffect, useRef, useState } from "react";

import type { ChatMessage } from "../hooks/useChat";
import { CopyButton } from "./CopyButton";
import { MarkdownMessage } from "./MarkdownMessage";
import { RoutingDetails } from "./RoutingDetails";

const NEAR_BOTTOM_THRESHOLD_PX = 96;

function MessageBubble({
  message,
  onRegenerate,
}: {
  message: ChatMessage;
  /** Set only on the last completed assistant message: re-asks the turn. */
  onRegenerate?: () => void;
}) {
  const isUser = message.role === "user";
  return (
    <div className={`group flex flex-col ${isUser ? "items-end" : "items-start"}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm sm:max-w-[75%] ${
          isUser
            ? "whitespace-pre-wrap bg-slate-900 text-white dark:bg-slate-200 dark:text-slate-900"
            : "border border-slate-200 bg-slate-100 text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
        }`}
      >
        {message.content ? (
          isUser ? (
            message.content
          ) : (
            <MarkdownMessage content={message.content} />
          )
        ) : message.statusNode ? (
          <span className="text-slate-500 italic dark:text-slate-400">Working: {message.statusNode}…</span>
        ) : (
          <span className="text-slate-500 italic dark:text-slate-400">Thinking…</span>
        )}
      </div>
      {!isUser && message.guardrailBlockedReason && (
        <span className="mt-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800 dark:bg-amber-950 dark:text-amber-300">
          {message.guardrailBlockedReason === "prompt_injection"
            ? "Blocked: this message was flagged as a prompt-injection attempt."
            : "Redacted: part of this answer looked like a leaked credential."}
        </span>
      )}
      {!isUser && message.content && (
        <div className="mt-1 flex items-center gap-2 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
          <CopyButton text={message.content} />
          {onRegenerate && (
            <button
              type="button"
              onClick={onRegenerate}
              className="rounded border border-slate-300 px-1.5 py-0.5 text-xs text-slate-500 hover:bg-slate-100 dark:border-slate-600 dark:text-slate-400 dark:hover:bg-slate-800"
            >
              Regenerate
            </button>
          )}
        </div>
      )}
      {!isUser && message.routingSummary && (
        <div className="max-w-[85%] sm:max-w-[75%]">
          <RoutingDetails summary={message.routingSummary} />
        </div>
      )}
    </div>
  );
}

export function ChatWindow({
  messages,
  isLoadingHistory = false,
  onRegenerate,
}: {
  messages: ChatMessage[];
  isLoadingHistory?: boolean;
  /** When set, the last completed assistant message gets a Regenerate
   * button that re-asks the turn's question. */
  onRegenerate?: () => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const prevMessageCountRef = useRef(0);
  // Tracks whether the user is near the bottom of the scroll area, so a
  // new message only auto-scrolls when they haven't deliberately
  // scrolled up to re-read earlier context - don't fight that choice.
  const [isNearBottom, setIsNearBottom] = useState(true);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    function handleScroll() {
      if (!container) return;
      const distanceFromBottom =
        container.scrollHeight - container.scrollTop - container.clientHeight;
      setIsNearBottom(distanceFromBottom < NEAR_BOTTOM_THRESHOLD_PX);
    }
    container.addEventListener("scroll", handleScroll);
    return () => container.removeEventListener("scroll", handleScroll);
  }, []);

  useEffect(() => {
    // Always scroll to the user's own freshly-sent message (a deliberate
    // action), but only follow an incoming/streaming assistant update if
    // the user hasn't scrolled up to re-read earlier context. A
    // conversation restored in one update (empty -> populated, i.e. a
    // switch or page load) starts at its latest message instantly.
    const lastMessage = messages[messages.length - 1];
    const justSentByUser = lastMessage?.role === "user";
    const justRestored = prevMessageCountRef.current === 0 && messages.length > 0;
    prevMessageCountRef.current = messages.length;
    if (justRestored) {
      bottomRef.current?.scrollIntoView({ block: "end" });
    } else if (isNearBottom || justSentByUser) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }

    // Re-measure once this message-list change has been laid out:
    // clearing or switching a conversation fires no scroll event, so
    // without this a stale "scrolled up" state from the previous
    // conversation keeps "Jump to latest" visible over a window with
    // nothing actually hidden below it.
    const frame = requestAnimationFrame(() => {
      const container = containerRef.current;
      if (
        container &&
        container.scrollHeight - container.clientHeight < NEAR_BOTTOM_THRESHOLD_PX
      ) {
        setIsNearBottom(true);
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [messages, isNearBottom]);

  function scrollToBottom() {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }

  return (
    <div className="relative flex-1 overflow-hidden">
      <div
        ref={containerRef}
        data-testid="chat-scroll-region"
        className="h-full space-y-4 overflow-y-auto px-4 py-6"
      >
        {messages.length === 0 && (
          <p className="mt-10 text-center text-sm text-slate-400 dark:text-slate-500">
            {isLoadingHistory
              ? "Loading conversation…"
              : "Ask a question about appliance troubleshooting to get started."}
          </p>
        )}
        {messages.map((message, index) => (
          <MessageBubble
            key={message.id}
            message={message}
            onRegenerate={
              index === messages.length - 1 && message.role === "assistant" && message.content
                ? onRegenerate
                : undefined
            }
          />
        ))}
        <div ref={bottomRef} />
      </div>
      {!isNearBottom && (
        <button
          type="button"
          onClick={scrollToBottom}
          className="absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full bg-slate-900 px-3 py-1.5 text-xs text-white shadow-lg dark:bg-slate-200 dark:text-slate-900"
        >
          Jump to latest ↓
        </button>
      )}
    </div>
  );
}
