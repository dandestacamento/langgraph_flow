/**
 * Knowledge Base Manager (chat-ui-plan5.md Phase B): upload documents
 * into the ingestion pipeline, watch their per-node progress, and fix
 * misclassifications (needs_review) with a manual topic/subtopic
 * override. Lazy-loaded from App.tsx - chat users who never open it
 * pay nothing for it.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchKnowledgeTaxonomy,
  getKnowledgeDocument,
  listKnowledgeDocuments,
  overrideClassification,
  reindexKnowledgeDocument,
  refreshClassificationSuggestion,
  uploadKnowledgeDocument,
} from "../api/client";
import type { KnowledgeDocument } from "../api/client";

const POLL_INTERVAL_MS = 2000;

const STATUS_STYLES: Record<KnowledgeDocument["status"], string> = {
  processing:
    "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  indexed:
    "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  needs_review:
    "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  failed: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
};

const STATUS_LABELS: Record<KnowledgeDocument["status"], string> = {
  processing: "Processing",
  indexed: "Indexed",
  needs_review: "Needs review",
  failed: "Failed",
};

function StatusBadge({ status }: { status: KnowledgeDocument["status"] }) {
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
        STATUS_STYLES[status] ?? "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300"
      }`}
    >
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

/** Manual topic/subtopic correction form. Options come from the backend taxonomy. */
function OverrideForm({
  document,
  taxonomy,
  onOverridden,
  onTaxonomyChanged,
}: {
  document: KnowledgeDocument;
  taxonomy: Record<string, string[]>;
  onOverridden: (updated: KnowledgeDocument) => void;
  onTaxonomyChanged: (taxonomy: Record<string, string[]>) => void;
}) {
  const topics = Object.keys(taxonomy);
  const [topic, setTopic] = useState(topics[0] ?? "");
  const [subtopic, setSubtopic] = useState(taxonomy[topics[0] ?? ""]?.[0] ?? "");
  const [newTopic, setNewTopic] = useState(false);
  const [newSubtopic, setNewSubtopic] = useState(false);
  const [customTopic, setCustomTopic] = useState("");
  const [customSubtopic, setCustomSubtopic] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (selectedTopic: string, selectedSubtopic: string) => {
    setSubmitting(true);
    setError(null);
    try {
      const createMissing = !(taxonomy[selectedTopic] ?? []).includes(selectedSubtopic);
      const updated = await overrideClassification(
        document.document_id, selectedTopic, selectedSubtopic, createMissing,
      );
      if (createMissing) {
        onTaxonomyChanged({
          ...taxonomy,
          [selectedTopic]: [...(taxonomy[selectedTopic] ?? []), selectedSubtopic],
        });
      }
      onOverridden(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Override failed.");
    } finally {
      setSubmitting(false);
    }
  };

  const refresh = async () => {
    setSubmitting(true);
    setError(null);
    try {
      onOverridden(await refreshClassificationSuggestion(document.document_id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Suggestion refresh failed.");
    } finally {
      setSubmitting(false);
    }
  };
  const chosenTopic = newTopic ? customTopic : topic;
  const chosenSubtopic = newTopic || newSubtopic ? customSubtopic : subtopic;
  const suggestion = document.pending ?? document;

  return (
    <div className="mt-2 rounded border border-amber-300 bg-amber-50 p-3 dark:border-amber-800 dark:bg-amber-950/40">
      <p className="mb-2 text-xs font-medium text-amber-800 dark:text-amber-300">
        {document.status === "indexed"
          ? "Choose a corrected classification:"
          : "Review the suggested classification or choose your own:"}
      </p>
      {document.status !== "indexed" && suggestion.topic && suggestion.subtopic && (
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <span>Suggested: <strong>{suggestion.topic} / {suggestion.subtopic}</strong></span>
          <button type="button" disabled={submitting} onClick={() => void submit(suggestion.topic!, suggestion.subtopic!)}
            className="rounded bg-amber-600 px-2 py-1 text-xs font-medium text-white hover:bg-amber-700 disabled:opacity-50">
            Approve suggestion &amp; index
          </button>
        </div>
      )}
      {document.status === "needs_review" && (
        <button type="button" disabled={submitting} onClick={() => void refresh()}
          className="mb-2 text-xs text-sky-700 underline disabled:opacity-50 dark:text-sky-300">
          Get a fresh suggestion
        </button>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-xs text-slate-600 dark:text-slate-300">
          Topic{" "}
          {newTopic ? (
            <input aria-label="New topic" value={customTopic} onChange={(e) => setCustomTopic(e.target.value)}
              placeholder="e.g. artificial_intelligence" className="rounded border border-slate-300 px-1 py-0.5 text-xs dark:bg-slate-800" />
          ) : (
          <select
            value={topic}
            onChange={(e) => {
              setTopic(e.target.value);
              setSubtopic(taxonomy[e.target.value]?.[0] ?? "");
            }}
            className="rounded border border-slate-300 bg-white px-1 py-0.5 text-xs dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200"
          >
            {topics.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          )}
        </label>
        <button type="button" onClick={() => setNewTopic(!newTopic)} className="text-xs text-sky-700 underline dark:text-sky-300">
          {newTopic ? "Choose existing topic" : "Create topic"}
        </button>
        <label className="text-xs text-slate-600 dark:text-slate-300">
          Subtopic{" "}
          {newTopic || newSubtopic ? (
            <input aria-label="New subtopic" value={customSubtopic} onChange={(e) => setCustomSubtopic(e.target.value)}
              placeholder="e.g. risk_management" className="rounded border border-slate-300 px-1 py-0.5 text-xs dark:bg-slate-800" />
          ) : (
          <select
            value={subtopic}
            onChange={(e) => setSubtopic(e.target.value)}
            className="rounded border border-slate-300 bg-white px-1 py-0.5 text-xs dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200"
          >
            {(taxonomy[topic] ?? []).map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          )}
        </label>
        {!newTopic && (
          <button type="button" onClick={() => setNewSubtopic(!newSubtopic)} className="text-xs text-sky-700 underline dark:text-sky-300">
            {newSubtopic ? "Choose existing subtopic" : "Create subtopic"}
          </button>
        )}
        <button
          type="button"
          onClick={() => void submit(chosenTopic, chosenSubtopic)}
          disabled={submitting || !chosenTopic || !chosenSubtopic}
          className="rounded bg-amber-600 px-2 py-1 text-xs font-medium text-white hover:bg-amber-700 disabled:opacity-50"
        >
          {submitting ? "Reclassifying…" : "Reclassify & index"}
        </button>
      </div>
      <p className="mt-2 text-xs text-slate-600 dark:text-slate-300">
        New names must use lowercase letters, digits and underscores.
      </p>
      {error && <p className="mt-2 text-xs text-red-600 dark:text-red-400">{error}</p>}
    </div>
  );
}

function DocumentDetail({
  document,
  taxonomy,
  onUpdated,
  onTaxonomyChanged,
}: {
  document: KnowledgeDocument;
  taxonomy: Record<string, string[]>;
  onUpdated: (updated: KnowledgeDocument) => void;
  onTaxonomyChanged: (taxonomy: Record<string, string[]>) => void;
}) {
  const [reindexing, setReindexing] = useState(false);
  const [reindexError, setReindexError] = useState<string | null>(null);

  const reindex = async () => {
    setReindexing(true);
    setReindexError(null);
    try {
      onUpdated(await reindexKnowledgeDocument(document.document_id));
    } catch (err) {
      setReindexError(err instanceof Error ? err.message : "Re-index failed.");
    } finally {
      setReindexing(false);
    }
  };

  return (
    <div className="border-t border-slate-100 px-3 py-2 text-xs dark:border-slate-800">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-slate-600 dark:text-slate-300 sm:grid-cols-3">
        <div>
          <dt className="font-medium text-slate-400 dark:text-slate-500">Classification</dt>
          <dd>
            {document.topic ? `${document.topic} / ${document.subtopic}` : "—"}
            {document.classification_confidence != null &&
              ` (${Math.round(document.classification_confidence * 100)}%)`}
          </dd>
        </div>
        <div>
          <dt className="font-medium text-slate-400 dark:text-slate-500">Chunks</dt>
          <dd>{document.chunk_count}</dd>
        </div>
        <div>
          <dt className="font-medium text-slate-400 dark:text-slate-500">Version</dt>
          <dd>v{document.version}</dd>
        </div>
      </dl>
      {document.pending && (
        <p className="mt-2 text-sky-700 dark:text-sky-300">
          Version {document.version} remains indexed while replacement version {document.pending.version} is processed or reviewed.
        </p>
      )}
      {document.status === "indexed" && !document.pending && document.chunk_count > 0 && (
        <div className="mt-2">
          <button type="button" disabled={reindexing} onClick={() => void reindex()}
            className="rounded bg-sky-600 px-2 py-1 text-xs font-medium text-white hover:bg-sky-700 disabled:opacity-50">
            {reindexing ? "Starting re-index…" : "Re-index stored file"}
          </button>
          <p className="mt-1 text-slate-500 dark:text-slate-400">
            Reclassifies the stored file, even if unchanged. The current version remains available until the new version is ready.
          </p>
        </div>
      )}
      {reindexError && <p role="alert" className="mt-2 text-red-600 dark:text-red-400">{reindexError}</p>}
      {document.error && (
        <p className="mt-2 rounded bg-red-50 px-2 py-1 text-red-700 dark:bg-red-950/40 dark:text-red-400">
          {document.error}
        </p>
      )}
      {(document.status === "needs_review" || document.status === "failed" ||
        (document.status === "indexed" && !document.pending)) && (
        <OverrideForm document={document} taxonomy={taxonomy} onOverridden={onUpdated} onTaxonomyChanged={onTaxonomyChanged} />
      )}
      {document.events.length > 0 && (
        <div className="mt-2">
          <p className="font-medium text-slate-400 dark:text-slate-500">Pipeline log</p>
          <ol className="mt-1 space-y-0.5">
            {document.events.map((event, i) => (
              <li key={i} className="flex gap-2">
                <span className="w-36 shrink-0 font-mono">{event.node}</span>
                <span className="w-16 shrink-0 text-right tabular-nums text-slate-400 dark:text-slate-500">
                  {event.elapsed_ms} ms
                </span>
                <span className="min-w-0 break-words">{event.detail}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

function KnowledgeBaseManager() {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [taxonomy, setTaxonomy] = useState<Record<string, string[]>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const upsert = useCallback((updated: KnowledgeDocument) => {
    setDocuments((prev) => {
      const index = prev.findIndex((d) => d.document_id === updated.document_id);
      if (index === -1) return [updated, ...prev];
      const next = [...prev];
      next[index] = updated;
      return next;
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([listKnowledgeDocuments(), fetchKnowledgeTaxonomy()])
      .then(([docs, tax]) => {
        if (cancelled) return;
        setDocuments(docs);
        setTaxonomy(tax);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load documents.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // While any document is still processing, poll just those documents
  // every 2s so statuses settle without a manual refresh.
  const processingIds = documents
    .filter((d) => d.status === "processing")
    .map((d) => d.document_id)
    .join(",");
  useEffect(() => {
    if (!processingIds) return;
    const ids = processingIds.split(",");
    const timer = setInterval(() => {
      for (const id of ids) {
        getKnowledgeDocument(id)
          .then(upsert)
          .catch(() => {
            // Transient polling failure - the next tick retries.
          });
      }
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [processingIds, upsert]);

  const handleFiles = useCallback(
    async (files: FileList | File[]) => {
      setUploading(true);
      setError(null);
      setNotice(null);
      for (const file of Array.from(files)) {
        try {
          const uploaded = await uploadKnowledgeDocument(file);
          upsert(uploaded);
          if (uploaded.duplicate) {
            setNotice(`"${file.name}" is unchanged. To process it again, expand its details and select Re-index stored file.`);
          } else if (uploaded.pending) {
            setNotice(`"${file.name}" is being reclassified as version ${uploaded.pending.version}; the previous version remains indexed.`);
          }
          setExpandedId(uploaded.document_id);
        } catch (err) {
          setError(err instanceof Error ? err.message : `Upload of ${file.name} failed.`);
        }
      }
      setUploading(false);
    },
    [upsert],
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 py-4">
      <section
        aria-label="Upload documents"
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (e.dataTransfer.files.length > 0) void handleFiles(e.dataTransfer.files);
        }}
        className={`rounded-lg border-2 border-dashed p-6 text-center text-sm transition-colors ${
          dragging
            ? "border-sky-400 bg-sky-50 dark:border-sky-600 dark:bg-sky-950/40"
            : "border-slate-300 text-slate-500 dark:border-slate-700 dark:text-slate-400"
        }`}
      >
        <p>
          Drop a PDF, Markdown, or text file here to add it to the knowledge base, or{" "}
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="font-medium text-sky-600 underline hover:text-sky-700 disabled:opacity-50 dark:text-sky-400"
          >
            browse
          </button>
          .
        </p>
        <p className="mt-1 text-xs">
          Documents are classified, chunked, and indexed automatically; low-confidence
          classifications are parked for your review. A changed file with the same name replaces
          the indexed version after the new version is ready.
        </p>
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.md,.markdown,.txt,.csv,.json,.yaml,.yml"
          multiple
          className="hidden"
          aria-label="Choose documents to ingest"
          onChange={(e) => {
            if (e.target.files && e.target.files.length > 0) void handleFiles(e.target.files);
            e.target.value = "";
          }}
        />
        {uploading && <p className="mt-2 text-xs text-sky-600 dark:text-sky-400">Uploading…</p>}
      </section>

      {notice && (
        <p role="status" className="text-xs text-slate-500 dark:text-slate-400">
          {notice}
        </p>
      )}
      {error && (
        <p role="alert" className="text-xs text-red-600 dark:text-red-400">
          {error}
        </p>
      )}

      {loading ? (
        <p className="text-sm text-slate-500 dark:text-slate-400">Loading documents…</p>
      ) : documents.length === 0 ? (
        <p className="text-sm text-slate-500 dark:text-slate-400">
          No documents ingested yet. Everything the assistant can currently answer comes from
          the curated knowledge base.
        </p>
      ) : (
        <ul className="space-y-2">
          {documents.map((doc) => (
            <li
              key={doc.document_id}
              className="rounded-lg border border-slate-200 dark:border-slate-700"
            >
              <button
                type="button"
                onClick={() =>
                  setExpandedId((prev) => (prev === doc.document_id ? null : doc.document_id))
                }
                aria-expanded={expandedId === doc.document_id}
                className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left hover:bg-slate-50 dark:hover:bg-slate-900"
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium text-slate-800 dark:text-slate-200">
                    {doc.filename}
                  </span>
                  <span className="block text-xs text-slate-400 dark:text-slate-500">
                    {formatSize(doc.size_bytes)}
                    {doc.topic && ` · ${doc.topic}/${doc.subtopic}`}
                  </span>
                </span>
                <StatusBadge status={doc.status} />
              </button>
              {expandedId === doc.document_id && (
                <DocumentDetail document={doc} taxonomy={taxonomy} onUpdated={upsert} onTaxonomyChanged={setTaxonomy} />
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default KnowledgeBaseManager;
