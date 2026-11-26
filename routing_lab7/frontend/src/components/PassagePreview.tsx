import { useEffect } from "react";

import type { RetrievedPassage } from "../api/client";

/** A retrieved passage plus the topic it was retrieved for - what a
 * citation chip opens (chat-ui-plan3.md §2 item 1 / chat-ui-plan2.md
 * §4: "view retrieved evidence in a modal or side panel"). */
export interface SelectedPassage extends RetrievedPassage {
  topic: string;
}

/**
 * Right-side panel showing one cited passage in full - the evidence
 * behind an answer, without digging through the collapsed Routing
 * details. Escape, the close button, or the backdrop dismisses it.
 */
export function PassagePreview({
  passage,
  onClose,
}: {
  passage: SelectedPassage;
  onClose: () => void;
}) {
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <>
      <button
        type="button"
        aria-label="Close source preview"
        onClick={onClose}
        className="fixed inset-0 z-30 bg-slate-900/30"
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={`Source passage: ${passage.source ?? passage.chapter_id ?? "unknown chapter"}`}
        className="fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l border-slate-200 bg-white shadow-xl dark:border-slate-700 dark:bg-slate-900"
      >
        <header className="flex items-start justify-between gap-2 border-b border-slate-200 px-4 py-3 dark:border-slate-700">
          <div>
            <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              {passage.source ?? passage.chapter_id ?? "Source passage"}
            </h2>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {[passage.topic, passage.subtopic].filter(Boolean).join(" › ")}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-slate-300 px-2 py-0.5 text-xs font-medium text-slate-600 hover:bg-slate-100 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            Close
          </button>
        </header>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 border-b border-slate-200 px-4 py-3 text-xs dark:border-slate-700">
          {passage.source && (
            <>
              <dt className="text-slate-500 dark:text-slate-400">File</dt>
              <dd className="text-slate-700 dark:text-slate-300">{passage.source}</dd>
            </>
          )}
          {passage.page != null && (
            <>
              <dt className="text-slate-500 dark:text-slate-400">Page</dt>
              <dd className="text-slate-700 dark:text-slate-300">{passage.page}</dd>
            </>
          )}
          {passage.version != null && (
            <>
              <dt className="text-slate-500 dark:text-slate-400">Version</dt>
              <dd className="text-slate-700 dark:text-slate-300">{passage.version}</dd>
            </>
          )}
          {passage.document_id && (
            <>
              <dt className="text-slate-500 dark:text-slate-400">Document</dt>
              <dd className="text-slate-700 dark:text-slate-300">{passage.document_id}</dd>
            </>
          )}
          {passage.score != null && (
            <>
              <dt className="text-slate-500 dark:text-slate-400">Retrieval score</dt>
              <dd className="text-slate-700 dark:text-slate-300">
                {passage.score.toFixed(2)}
              </dd>
            </>
          )}
        </dl>
        <div className="flex-1 overflow-y-auto px-4 py-3">
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-800 dark:text-slate-200">
            {passage.text ?? "No passage text was recorded for this source."}
          </p>
        </div>
      </aside>
    </>
  );
}
