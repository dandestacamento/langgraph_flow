import { useRef, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";

const MAX_TEXTAREA_HEIGHT_PX = 160; // ~6 lines, then it scrolls

export function Composer({
  onSend,
  disabled,
  onStop,
}: {
  onSend: (text: string) => void;
  disabled: boolean;
  /** When provided and a send is in flight (`disabled`), a Stop button
   * replaces Send - cancels the client's wait, not the server's turn
   * (chat-ui-plan3.md §1.5). */
  onStop?: () => void;
}) {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  function submit() {
    if (!text.trim() || disabled) return;
    onSend(text);
    setText("");
    const textarea = textareaRef.current;
    if (textarea) textarea.style.height = "auto";
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    submit();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends, Shift+Enter inserts a newline (chat-ui-plan2.md) -
    // the ChatGPT-style convention.
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  function handleInput() {
    // Auto-expand up to MAX_TEXTAREA_HEIGHT_PX, then scroll inside.
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, MAX_TEXTAREA_HEIGHT_PX)}px`;
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex items-end gap-2 border-t border-slate-200 p-4 dark:border-slate-700"
    >
      <textarea
        ref={textareaRef}
        rows={1}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onInput={handleInput}
        onKeyDown={handleKeyDown}
        placeholder="Type your message…"
        aria-label="Type your message"
        disabled={disabled}
        className="max-h-40 flex-1 resize-none rounded-lg border border-slate-300 bg-white px-3 py-2 text-base text-slate-900 focus:outline-none focus:ring-2 focus:ring-slate-400 disabled:bg-slate-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100 dark:placeholder:text-slate-500 dark:disabled:bg-slate-900 sm:text-sm"
      />
      {disabled && onStop ? (
        <button
          type="button"
          onClick={onStop}
          className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800"
        >
          Stop
        </button>
      ) : (
        <button
          type="submit"
          disabled={disabled || !text.trim()}
          className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-300 dark:bg-slate-200 dark:text-slate-900 dark:disabled:bg-slate-700 dark:disabled:text-slate-500"
        >
          Send
        </button>
      )}
    </form>
  );
}
