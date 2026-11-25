import { useCallback, useEffect, useRef, useState } from "react";

import type { ChatMessage } from "../hooks/useChat";
import { CopyButton } from "./CopyButton";
import { MarkdownMessage } from "./MarkdownMessage";
import { MessageAttachments } from "./MessageAttachments";
import type { SelectedPassage } from "./PassagePreview";
import { RoutingDetails } from "./RoutingDetails";

const NEAR_BOTTOM_THRESHOLD_PX = 96;

// Human phrasing for graph node names shown while a turn streams
// (chat-ui-plan3.md §1.3) - falls back to the raw name for any node not
// listed, so new graph nodes degrade gracefully instead of breaking.
const NODE_STATUS_LABELS: Record<string, string> = {
  check_input: "Checking your message…",
  condense: "Understanding your question…",
  answer_from_history: "Reading our conversation…",
  invoke_routing_pipeline: "Searching the knowledge base…",
  check_output: "Checking the answer…",
  record_turn: "Saving this turn…",
};

function statusLabel(node: string): string {
  return NODE_STATUS_LABELS[node] ?? `Working: ${node}…`;
}

function MessageBubble({
  message,
  threadId,
  onRegenerate,
  onOpenPassage,
}: {
  message: ChatMessage;
  threadId?: string;
  /** Set only on the last completed assistant message: re-asks the turn. */
  onRegenerate?: () => void;
  /** Opens a cited passage in the preview panel (chat-ui-plan3.md §2) -
   * reached via the passage cards inside Routing details (a separate
   * chips row was tried first and removed as duplicative). */
  onOpenPassage?: (passage: SelectedPassage) => void;
}) {
  const isUser = message.role === "user";
  return (
    <div className={`group flex flex-col ${isUser ? "items-end" : "items-start"}`}>
      {isUser && message.attachments && threadId && (
        <MessageAttachments threadId={threadId} attachments={message.attachments} />
      )}
      {(message.content || !isUser) && (
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
        ) : message.stopped ? (
          <span className="text-slate-500 italic dark:text-slate-400">
            Stopped waiting for this answer. It may still finish on the server - reopen this
            conversation later to see it.
          </span>
        ) : message.statusNode ? (
          <span className="text-slate-500 italic dark:text-slate-400">{statusLabel(message.statusNode)}</span>
        ) : (
          <span className="text-slate-500 italic dark:text-slate-400">Thinking…</span>
        )}
      </div>
      )}
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
          <RoutingDetails
            summary={message.routingSummary}
            executionTrace={message.executionTrace}
            onOpenPassage={onOpenPassage}
          />
        </div>
      )}
    </div>
  );
}

export function ChatWindow({
  messages,
  threadId,
  isLoadingHistory = false,
  onRegenerate,
  starterPrompts,
  onStarterPrompt,
  onOpenPassage,
}: {
  messages: ChatMessage[];
  /** Active conversation id - needed to fetch attachment thumbnails. */
  threadId?: string;
  isLoadingHistory?: boolean;
  /** When set, the last completed assistant message gets a Regenerate
   * button that re-asks the turn's question. */
  onRegenerate?: () => void;
  /** Example questions shown as clickable chips on the empty state
   * (chat-ui-plan3.md §1.4) - reveals what the knowledge base covers. */
  starterPrompts?: string[];
  onStarterPrompt?: (prompt: string) => void;
  /** Opens a cited passage in the preview panel (chat-ui-plan3.md §2). */
  onOpenPassage?: (passage: SelectedPassage) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const prevMessageCountRef = useRef(0);
  // Tracks whether the user is near the bottom of the scroll area, so a
  // new message only auto-scrolls when they haven't deliberately
  // scrolled up to re-read earlier context - don't fight that choice.
  const [isNearBottom, setIsNearBottom] = useState(true);
  // Whether the conversation actually overflows the viewport - "Jump to
  // latest" is meaningless (and was observed lingering, e.g. after
  // collapsing Routing details) when everything already fits.
  const [isOverflowing, setIsOverflowing] = useState(false);

  const recomputeScrollState = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const maxScroll = container.scrollHeight - container.clientHeight;
    setIsOverflowing(maxScroll >= NEAR_BOTTOM_THRESHOLD_PX);
    setIsNearBottom(maxScroll - container.scrollTop < NEAR_BOTTOM_THRESHOLD_PX);
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    container.addEventListener("scroll", recomputeScrollState);
    // Content height also changes WITHOUT any scroll event or new
    // message - expanding/collapsing Routing details is the main case -
    // so watch for resizes too, or the state above goes stale.
    let observer: ResizeObserver | undefined;
    if (typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver(recomputeScrollState);
      observer.observe(container);
      if (contentRef.current) observer.observe(contentRef.current);
    }
    return () => {
      container.removeEventListener("scroll", recomputeScrollState);
      observer?.disconnect();
    };
  }, [recomputeScrollState]);

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
    const frame = requestAnimationFrame(recomputeScrollState);
    return () => cancelAnimationFrame(frame);
  }, [messages, isNearBottom, recomputeScrollState]);

  function scrollToBottom() {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }

  return (
    <div className="relative flex-1 overflow-hidden">
      <div
        ref={containerRef}
        data-testid="chat-scroll-region"
        className="h-full overflow-y-auto px-4 py-6"
      >
        {/* Inner wrapper exists so the ResizeObserver above can watch the
            content's height (e.g. Routing details collapsing). */}
        <div ref={contentRef} className="space-y-4">
        {messages.length === 0 && (
          <div className="mt-10 space-y-4">
            <p className="text-center text-sm text-slate-400 dark:text-slate-500">
              {isLoadingHistory
                ? "Loading conversation…"
                : "Ask a question about the knowledge base to get started."}
            </p>
            {!isLoadingHistory && starterPrompts && starterPrompts.length > 0 && (
              <div className="mx-auto flex max-w-md flex-wrap justify-center gap-2">
                {starterPrompts.map((prompt) => (
                  <button
                    key={prompt}
                    type="button"
                    onClick={() => onStarterPrompt?.(prompt)}
                    className="rounded-full border border-slate-300 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-100 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-800"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        {messages.map((message, index) => (
          <MessageBubble
            key={message.id}
            message={message}
            threadId={threadId}
            onOpenPassage={onOpenPassage}
            onRegenerate={
              index === messages.length - 1 && message.role === "assistant" && message.content
                ? onRegenerate
                : undefined
            }
          />
        ))}
        <div ref={bottomRef} />
        </div>
      </div>
      {isOverflowing && !isNearBottom && (
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
