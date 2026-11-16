import type { ChatMessage } from "../hooks/useChat";
import { RoutingDetails } from "./RoutingDetails";

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex flex-col ${isUser ? "items-end" : "items-start"}`}>
      <div
        className={`max-w-[75%] rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap ${
          isUser
            ? "bg-slate-900 text-white"
            : "bg-slate-100 text-slate-900 border border-slate-200"
        }`}
      >
        {message.content ? (
          message.content
        ) : message.statusNode ? (
          <span className="text-slate-500 italic">Working: {message.statusNode}…</span>
        ) : (
          <span className="text-slate-500 italic">Thinking…</span>
        )}
      </div>
      {!isUser && message.routingSummary && (
        <div className="max-w-[75%]">
          <RoutingDetails summary={message.routingSummary} />
        </div>
      )}
    </div>
  );
}

export function ChatWindow({ messages }: { messages: ChatMessage[] }) {
  return (
    <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4">
      {messages.length === 0 && (
        <p className="text-center text-slate-400 text-sm mt-10">
          Ask a question about appliance troubleshooting to get started.
        </p>
      )}
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}
    </div>
  );
}
