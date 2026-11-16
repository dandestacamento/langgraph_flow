import { useEffect, useRef, useState } from "react";

import type { ChatMessage } from "../hooks/useChat";
import { CopyButton } from "./CopyButton";
import { MarkdownMessage } from "./MarkdownMessage";
import { RoutingDetails } from "./RoutingDetails";

const NEAR_BOTTOM_THRESHOLD_PX = 96;

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={`group flex flex-col ${isUser ? "items-end" : "items-start"}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm sm:max-w-[75%] ${
          isUser
            ? "whitespace-pre-wrap bg-slate-900 text-white"
            : "border border-slate-200 bg-slate-100 text-slate-900"
        }`}
      >
        {message.content ? (
          isUser ? (
            message.content
          ) : (
            <MarkdownMessage content={message.content} />
          )
        ) : message.statusNode ? (
          <span className="text-slate-500 italic">Working: {message.statusNode}…</span>
        ) : (
          <span className="text-slate-500 italic">Thinking…</span>
        )}
      </div>
      {!isUser && message.guardrailBlockedReason && (
        <span className="mt-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800">
          {message.guardrailBlockedReason === "prompt_injection"
            ? "Blocked: this message was flagged as a prompt-injection attempt."
            : "Redacted: part of this answer looked like a leaked credential."}
        </span>
      )}
      {!isUser && message.content && (
        <div className="mt-1 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
          <CopyButton text={message.content} />
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

export function ChatWindow({ messages }: { messages: ChatMessage[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
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
    // the user hasn't scrolled up to re-read earlier context.
    const lastMessage = messages[messages.length - 1];
    const justSentByUser = lastMessage?.role === "user";
    if (isNearBottom || justSentByUser) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [messages, isNearBottom]);

  function scrollToBottom() {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }

  return (
    <div className="relative flex-1 overflow-hidden">
      <div ref={containerRef} className="h-full space-y-4 overflow-y-auto px-4 py-6">
        {messages.length === 0 && (
          <p className="mt-10 text-center text-sm text-slate-400">
            Ask a question about appliance troubleshooting to get started.
          </p>
        )}
        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}
        <div ref={bottomRef} />
      </div>
      {!isNearBottom && (
        <button
          type="button"
          onClick={scrollToBottom}
          className="absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full bg-slate-900 px-3 py-1.5 text-xs text-white shadow-lg"
        >
          Jump to latest ↓
        </button>
      )}
    </div>
  );
}
