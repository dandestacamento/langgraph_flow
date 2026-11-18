import { useRef, useState } from "react";
import type { ChangeEvent, ClipboardEvent, DragEvent, FormEvent, KeyboardEvent } from "react";

import type { AttachmentMeta } from "../api/client";

const MAX_TEXTAREA_HEIGHT_PX = 160; // ~6 lines, then it scrolls
const MAX_PENDING_ATTACHMENTS = 4; // mirrors the server-side cap
const MAX_IMAGE_EDGE_PX = 1568; // downscale bound (chat-ui-plan4.md §2.3)

interface PendingAttachment {
  localId: string;
  filename: string;
  objectUrl: string | null; // local preview (images)
  status: "uploading" | "ready" | "error";
  meta?: AttachmentMeta;
  error?: string;
}

/** Downscales an image to a bounded long edge before upload - smaller
 * uploads and bounded vision-call cost with no visible quality loss for
 * screenshots. Falls back to the original file where canvas APIs are
 * unavailable (jsdom, ancient browsers). */
async function downscaleImage(file: File | Blob): Promise<File | Blob> {
  if (typeof createImageBitmap !== "function") return file;
  try {
    const bitmap = await createImageBitmap(file);
    const longEdge = Math.max(bitmap.width, bitmap.height);
    if (longEdge <= MAX_IMAGE_EDGE_PX) return file;
    const scale = MAX_IMAGE_EDGE_PX / longEdge;
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    const context = canvas.getContext("2d");
    if (!context) return file;
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
    return blob ?? file;
  } catch {
    return file;
  }
}

export function Composer({
  onSend,
  disabled,
  onStop,
  onUpload,
}: {
  onSend: (text: string, attachments: AttachmentMeta[]) => void;
  disabled: boolean;
  /** When provided and a send is in flight (`disabled`), a Stop button
   * replaces Send - cancels the client's wait, not the server's turn
   * (chat-ui-plan3.md §1.5). */
  onStop?: () => void;
  /** Uploads one file to the active conversation and resolves its
   * metadata - wired to the backend by App (chat-ui-plan4.md Phase A).
   * When omitted, the attach affordances are hidden. */
  onUpload?: (file: File | Blob) => Promise<AttachmentMeta>;
}) {
  const [text, setText] = useState("");
  const [pending, setPending] = useState<PendingAttachment[]>([]);
  const [isDraggingOver, setIsDraggingOver] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const anyUploading = pending.some((p) => p.status === "uploading");
  const readyAttachments = pending.filter((p) => p.status === "ready" && p.meta);

  async function addFiles(files: Iterable<File>) {
    if (!onUpload) return;
    for (const file of files) {
      if (pending.length >= MAX_PENDING_ATTACHMENTS) break;
      const localId = crypto.randomUUID();
      const objectUrl = file.type.startsWith("image/") ? URL.createObjectURL(file) : null;
      setPending((prev) => [
        ...prev,
        { localId, filename: file.name || "pasted-image.png", objectUrl, status: "uploading" },
      ]);
      try {
        const upload = file.type.startsWith("image/") ? await downscaleImage(file) : file;
        const meta = await onUpload(
          upload instanceof File ? upload : new File([upload], file.name || "pasted-image.png"),
        );
        setPending((prev) =>
          prev.map((p) => (p.localId === localId ? { ...p, status: "ready", meta } : p)),
        );
      } catch (err) {
        setPending((prev) =>
          prev.map((p) =>
            p.localId === localId
              ? { ...p, status: "error", error: err instanceof Error ? err.message : "Upload failed" }
              : p,
          ),
        );
      }
    }
  }

  function removePending(localId: string) {
    setPending((prev) => {
      const target = prev.find((p) => p.localId === localId);
      if (target?.objectUrl) URL.revokeObjectURL(target.objectUrl);
      return prev.filter((p) => p.localId !== localId);
    });
  }

  function handlePaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const files = Array.from(event.clipboardData?.files ?? []);
    if (files.length > 0) {
      event.preventDefault(); // don't also paste a filename as text
      void addFiles(files);
    }
  }

  function handleDrop(event: DragEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsDraggingOver(false);
    void addFiles(Array.from(event.dataTransfer?.files ?? []));
  }

  function handleFilePick(event: ChangeEvent<HTMLInputElement>) {
    void addFiles(Array.from(event.target.files ?? []));
    event.target.value = ""; // allow re-picking the same file
  }

  function submit() {
    const attachments = readyAttachments.map((p) => p.meta as AttachmentMeta);
    if ((!text.trim() && attachments.length === 0) || disabled || anyUploading) return;
    onSend(text, attachments);
    setText("");
    pending.forEach((p) => p.objectUrl && URL.revokeObjectURL(p.objectUrl));
    setPending([]);
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

  const canSend = (text.trim().length > 0 || readyAttachments.length > 0) && !anyUploading;

  return (
    <form
      onSubmit={handleSubmit}
      onDragOver={(event) => {
        if (onUpload) {
          event.preventDefault();
          setIsDraggingOver(true);
        }
      }}
      onDragLeave={() => setIsDraggingOver(false)}
      onDrop={onUpload ? handleDrop : undefined}
      className={`border-t border-slate-200 p-4 dark:border-slate-700 ${
        isDraggingOver ? "bg-slate-100 dark:bg-slate-800" : ""
      }`}
    >
      {pending.length > 0 && (
        <ul className="mb-2 flex flex-wrap gap-2" aria-label="Pending attachments">
          {pending.map((p) => (
            <li
              key={p.localId}
              className={`flex items-center gap-2 rounded-lg border px-2 py-1 text-xs ${
                p.status === "error"
                  ? "border-red-300 text-red-700 dark:border-red-800 dark:text-red-400"
                  : "border-slate-300 text-slate-700 dark:border-slate-600 dark:text-slate-300"
              }`}
            >
              {p.objectUrl && (
                <img src={p.objectUrl} alt="" className="h-8 w-8 rounded object-cover" />
              )}
              <span className="max-w-40 truncate">{p.filename}</span>
              {p.status === "uploading" && <span className="text-slate-400">uploading…</span>}
              {p.status === "error" && <span>{p.error}</span>}
              <button
                type="button"
                aria-label={`Remove attachment ${p.filename}`}
                onClick={() => removePending(p.localId)}
                className="font-semibold hover:text-red-600"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex items-end gap-2">
        {onUpload && (
          <>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp,image/gif"
              multiple
              hidden
              onChange={handleFilePick}
              aria-label="Attach files"
            />
            <button
              type="button"
              aria-label="Add photos and files"
              title="Add photos & files (or paste/drop them)"
              disabled={disabled || pending.length >= MAX_PENDING_ATTACHMENTS}
              onClick={() => fileInputRef.current?.click()}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              +
            </button>
          </>
        )}
        <textarea
          ref={textareaRef}
          rows={1}
          value={text}
          onChange={(event) => setText(event.target.value)}
          onInput={handleInput}
          onKeyDown={handleKeyDown}
          onPaste={onUpload ? handlePaste : undefined}
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
            disabled={disabled || !canSend}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-300 dark:bg-slate-200 dark:text-slate-900 dark:disabled:bg-slate-700 dark:disabled:text-slate-500"
          >
            Send
          </button>
        )}
      </div>
    </form>
  );
}
