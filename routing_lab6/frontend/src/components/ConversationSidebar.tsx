import { useState } from "react";
import type { FormEvent } from "react";

import type { ThreadSummary } from "../api/client";

interface ConversationSidebarProps {
  threads: ThreadSummary[];
  activeThreadId: string;
  /** Disable switching/creating while a send is in flight - switching
   * mid-stream would orphan the streaming update's target message. */
  disabled?: boolean;
  onSelect: (threadId: string) => void;
  onNew: () => void;
  onRename: (threadId: string, title: string) => void;
  onDelete: (threadId: string) => void;
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

function RenameForm({
  initialTitle,
  onSave,
  onCancel,
}: {
  initialTitle: string;
  onSave: (title: string) => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState(initialTitle);

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (draft.trim()) onSave(draft);
    else onCancel();
  }

  return (
    <form onSubmit={handleSubmit} className="px-1 py-1">
      <input
        autoFocus
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") onCancel();
        }}
        onBlur={onCancel}
        aria-label="Conversation title"
        className="w-full rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-slate-400 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
      />
    </form>
  );
}

/**
 * The conversation list/switcher (chat-ui-plan1.md Phase E), with
 * search/rename/delete management (chat-ui-plan2.md). Default export so
 * App.tsx can `React.lazy` it - it isn't needed for first paint of the
 * chat itself.
 */
export function ConversationSidebar({
  threads,
  activeThreadId,
  disabled = false,
  onSelect,
  onNew,
  onRename,
  onDelete,
}: ConversationSidebarProps) {
  const [query, setQuery] = useState("");
  const [renamingId, setRenamingId] = useState<string | null>(null);
  // Two-step inline delete: first click arms, second click confirms -
  // no native confirm() dialog to fight in tests or on mobile.
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null);

  const visibleThreads = query.trim()
    ? threads.filter((t) => t.title.toLowerCase().includes(query.trim().toLowerCase()))
    : threads;

  return (
    <nav
      aria-label="Conversations"
      className="flex h-full flex-col gap-3 overflow-y-auto border-r border-slate-200 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-900"
    >
      <button
        type="button"
        onClick={onNew}
        disabled={disabled}
        className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
      >
        + New conversation
      </button>
      {threads.length > 0 && (
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search conversations…"
          aria-label="Search conversations"
          className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-400 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100 dark:placeholder:text-slate-500"
        />
      )}
      {threads.length === 0 ? (
        <p className="px-1 text-xs text-slate-600 dark:text-slate-400">No past conversations yet.</p>
      ) : visibleThreads.length === 0 ? (
        <p className="px-1 text-xs text-slate-600 dark:text-slate-400">No conversations match your search.</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {visibleThreads.map((thread) => {
            const isActive = thread.thread_id === activeThreadId;
            if (renamingId === thread.thread_id) {
              return (
                <li key={thread.thread_id}>
                  <RenameForm
                    initialTitle={thread.title}
                    onSave={(title) => {
                      onRename(thread.thread_id, title);
                      setRenamingId(null);
                    }}
                    onCancel={() => setRenamingId(null)}
                  />
                </li>
              );
            }
            return (
              <li key={thread.thread_id} className="group relative">
                <button
                  type="button"
                  onClick={() => onSelect(thread.thread_id)}
                  disabled={disabled}
                  aria-current={isActive ? "true" : undefined}
                  className={`w-full rounded-lg px-3 py-2 pr-16 text-left disabled:cursor-not-allowed disabled:opacity-50 ${
                    isActive
                      ? "bg-slate-900 text-white dark:bg-slate-200 dark:text-slate-900"
                      : "text-slate-700 hover:bg-slate-200 dark:text-slate-300 dark:hover:bg-slate-800"
                  }`}
                >
                  <span className="block truncate text-sm">
                    {thread.title || "Untitled conversation"}
                  </span>
                  <span
                    className={`block text-xs ${
                      isActive
                        ? "text-slate-300 dark:text-slate-600"
                        : "text-slate-600 dark:text-slate-500"
                    }`}
                  >
                    {formatRelativeTime(thread.updated_at)}
                  </span>
                </button>
                <div className="absolute right-1.5 top-1/2 flex -translate-y-1/2 gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
                  {confirmingDeleteId === thread.thread_id ? (
                    <button
                      type="button"
                      onClick={() => {
                        onDelete(thread.thread_id);
                        setConfirmingDeleteId(null);
                      }}
                      onBlur={() => setConfirmingDeleteId(null)}
                      disabled={disabled}
                      className="rounded border border-red-300 bg-red-50 px-1.5 py-0.5 text-xs font-medium text-red-700 hover:bg-red-100 dark:border-red-800 dark:bg-red-950 dark:text-red-300"
                    >
                      Confirm?
                    </button>
                  ) : (
                    <>
                      <button
                        type="button"
                        aria-label={`Rename conversation: ${thread.title}`}
                        onClick={() => setRenamingId(thread.thread_id)}
                        disabled={disabled}
                        className={`rounded px-1 py-0.5 text-xs ${
                          isActive
                            ? "text-slate-300 hover:bg-slate-700 dark:text-slate-600 dark:hover:bg-slate-300"
                            : "text-slate-500 hover:bg-slate-300 dark:text-slate-400 dark:hover:bg-slate-700"
                        }`}
                      >
                        ✎
                      </button>
                      <button
                        type="button"
                        aria-label={`Delete conversation: ${thread.title}`}
                        onClick={() => setConfirmingDeleteId(thread.thread_id)}
                        disabled={disabled}
                        className={`rounded px-1 py-0.5 text-xs ${
                          isActive
                            ? "text-slate-300 hover:bg-slate-700 dark:text-slate-600 dark:hover:bg-slate-300"
                            : "text-slate-500 hover:bg-slate-300 dark:text-slate-400 dark:hover:bg-slate-700"
                        }`}
                      >
                        🗑
                      </button>
                    </>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </nav>
  );
}

export default ConversationSidebar;
