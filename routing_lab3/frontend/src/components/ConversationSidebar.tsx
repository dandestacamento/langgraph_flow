import type { ThreadSummary } from "../api/client";

interface ConversationSidebarProps {
  threads: ThreadSummary[];
  activeThreadId: string;
  /** Disable switching/creating while a send is in flight - switching
   * mid-stream would orphan the streaming update's target message. */
  disabled?: boolean;
  onSelect: (threadId: string) => void;
  onNew: () => void;
}

function formatRelativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const minutes = Math.round((Date.now() - then) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return new Date(iso).toLocaleDateString();
}

/**
 * The conversation list/switcher (chat-ui-plan1.md Phase E). Default
 * export so App.tsx can `React.lazy` it - it isn't needed for first
 * paint of the chat itself (chat-ui-plan1.md section 2.6 called out
 * exactly this component as the code-splitting candidate).
 */
export function ConversationSidebar({
  threads,
  activeThreadId,
  disabled = false,
  onSelect,
  onNew,
}: ConversationSidebarProps) {
  return (
    <nav
      aria-label="Conversations"
      className="flex h-full flex-col gap-3 overflow-y-auto border-r border-slate-200 bg-slate-50 p-3"
    >
      <button
        type="button"
        onClick={onNew}
        disabled={disabled}
        className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
      >
        + New conversation
      </button>
      {threads.length === 0 ? (
        <p className="px-1 text-xs text-slate-600">No past conversations yet.</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {threads.map((thread) => {
            const isActive = thread.thread_id === activeThreadId;
            return (
              <li key={thread.thread_id}>
                <button
                  type="button"
                  onClick={() => onSelect(thread.thread_id)}
                  disabled={disabled}
                  aria-current={isActive ? "true" : undefined}
                  className={`w-full rounded-lg px-3 py-2 text-left disabled:cursor-not-allowed disabled:opacity-50 ${
                    isActive
                      ? "bg-slate-900 text-white"
                      : "text-slate-700 hover:bg-slate-200"
                  }`}
                >
                  <span className="block truncate text-sm">
                    {thread.title || "Untitled conversation"}
                  </span>
                  <span
                    className={`block text-xs ${isActive ? "text-slate-300" : "text-slate-600"}`}
                  >
                    {formatRelativeTime(thread.updated_at)}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </nav>
  );
}

export default ConversationSidebar;
