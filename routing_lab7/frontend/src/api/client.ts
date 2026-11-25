/**
 * Typed client for routing_lab7's custom FastAPI backend
 * (app/api/main.py) - NOT the official LangGraph Server protocol (see
 * instructions/learnings/routing-lab-prod-plan.md section 0/2.10 for why
 * this project uses its own minimal API instead of that packaged
 * server). Endpoints and payload shapes here must stay in sync with
 * app/api/main.py's `ChatRequest`/`ChatResponse` models and its two
 * routes, `/chat` and `/chat/stream`.
 */

import { getValidToken } from "../auth/keycloak";

// In dev, Vite's server.proxy (vite.config.ts) forwards "/api/*" to the
// FastAPI backend on localhost:8000, so this works out of the box with
// no CORS configuration. Override via VITE_API_BASE_URL for other
// deployments (e.g. a separately hosted backend in production).
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api";

export interface RetrievedPassage {
  chapter_id: string | null;
  document_id: string | null;
  source?: string | null;
  version?: number | null;
  page?: number | null;
  subtopic: string | null;
  score: number | null;
  text: string | null;
}

export interface ToolResult {
  tool_name: string;
  tool_input: string;
  output: string | null;
  error: string | null;
}

export interface HopResult {
  hop_number: number;
  question: string;
  final_answer: string;
  extracted_value: string | null;
}

export interface RecoveryAttempt {
  attempted: boolean;
  reason: string | null;
  succeeded: boolean | null;
}

/** Trimmed per-turn routing/retrieval/tool trace - mirrors
 * app/chat/routing_summary.py's `build_routing_summary` output exactly. */
export interface RoutingSummary {
  topics: string[];
  subtopics: Record<string, string>;
  chapters: Record<string, string>;
  passages: Record<string, RetrievedPassage[]>;
  tool_results: Record<string, ToolResult>;
  is_multi_hop: boolean;
  hop_results: HopResult[];
  recovery_attempts: Record<string, RecoveryAttempt>;
}

export interface ChatResponse {
  thread_id: string;
  self_contained_question: string;
  final_answer: string;
  routing_summary: RoutingSummary;
  guardrail_blocked_reason?: string | null;
}

/** One row of the authenticated user's conversation list - mirrors
 * app/api/main.py's `ThreadSummary`. */
export interface ThreadSummary {
  thread_id: string;
  title: string;
  updated_at: string;
}

/** One restored past turn of a conversation - mirrors app/api/main.py's
 * `ThreadHistoryTurn`. `routing_summary` is `{}` and `attachments` `[]`
 * for turns recorded before those fields were persisted. */
export interface ThreadHistoryTurn {
  user_message: string;
  final_answer: string;
  routing_summary?: RoutingSummary | Record<string, never>;
  attachments?: AttachmentMeta[];
}

/** Metadata for an uploaded attachment - mirrors app/api/main.py's
 * `AttachmentMeta` (chat-ui-plan4.md Phase A/B). `extracted_chars === 0`
 * on a document means no readable text (e.g. a scanned PDF). */
export interface AttachmentMeta {
  attachment_id: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  extracted_chars?: number;
}

export interface StreamStatusEvent {
  type: "status";
  node: string;
  /** Time spent since the previous event - roughly this node's own
   * duration (chat-ui-plan3.md §2.2's execution timeline). */
  elapsedMs?: number;
}

export interface StreamAnswerEvent {
  type: "answer";
  final_answer: string;
  routing_summary: RoutingSummary;
  guardrail_blocked_reason?: string | null;
}

export type StreamEvent = StreamStatusEvent | StreamAnswerEvent;

/** One step of a turn's node-by-node execution timeline, accumulated
 * from status events (chat-ui-plan3.md §2.2). */
export interface ExecutionStep {
  node: string;
  elapsedMs?: number;
}

/** One synchronous turn: POST /chat, waits for the complete answer. */
export async function sendChatMessage(
  threadId: string,
  message: string,
  attachmentIds: string[] = [],
): Promise<ChatResponse> {
  const token = await getValidToken();
  const response = await fetch(`${API_BASE_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ thread_id: threadId, message, attachment_ids: attachmentIds }),
  });
  if (!response.ok) {
    throw new Error(`Chat request failed: ${response.status} ${response.statusText}`);
  }
  return response.json();
}

/**
 * One streamed turn: POST /chat/stream, parses the backend's
 * `text/event-stream` body (one `status` event per completed graph
 * node, then a final `answer` event) and invokes `onEvent` for each.
 * `fetch` + a manual reader is used instead of `EventSource`, since
 * `EventSource` cannot send a POST body.
 */
export async function streamChatMessage(
  threadId: string,
  message: string,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
  attachmentIds: string[] = [],
): Promise<void> {
  const token = await getValidToken();
  const response = await fetch(`${API_BASE_URL}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ thread_id: threadId, message, attachment_ids: attachmentIds }),
    signal,
  });
  if (!response.ok || !response.body) {
    throw new Error(`Chat stream request failed: ${response.status} ${response.statusText}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line; each frame has an
    // "event: <name>" line and a "data: <json>" line.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const eventLine = frame.split("\n").find((line) => line.startsWith("event: "));
      const dataLine = frame.split("\n").find((line) => line.startsWith("data: "));
      if (!eventLine || !dataLine) continue;
      const eventName = eventLine.slice("event: ".length).trim();
      const data = JSON.parse(dataLine.slice("data: ".length));
      if (eventName === "status") {
        onEvent({ type: "status", node: data.node, elapsedMs: data.elapsed_ms });
      } else if (eventName === "answer") {
        onEvent({
          type: "answer",
          final_answer: data.final_answer,
          routing_summary: data.routing_summary,
          guardrail_blocked_reason: data.guardrail_blocked_reason ?? null,
        });
      } else if (eventName === "error") {
        // Emitted when the backend's LLM gateway rejects a call
        // mid-stream (e.g. a budget-exceeded user) - thrown rather than
        // delivered via onEvent so it flows through the same
        // catch/describeError path as every other failure (useChat.ts).
        throw new Error(data.detail ?? "The assistant could not complete this response.");
      }
    }
  }
}

/** The authenticated user's conversations, most recently active first:
 * GET /threads. */
export async function listThreads(): Promise<ThreadSummary[]> {
  const token = await getValidToken();
  const response = await fetch(`${API_BASE_URL}/threads`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw new Error(`Thread list request failed: ${response.status} ${response.statusText}`);
  }
  return response.json();
}

/** Past turns of one conversation: GET /threads/{id}/history. A 404
 * (a brand-new thread_id the backend hasn't seen a message for yet)
 * is a normal empty conversation, not an error. */
export async function fetchThreadHistory(threadId: string): Promise<ThreadHistoryTurn[]> {
  const token = await getValidToken();
  const response = await fetch(
    `${API_BASE_URL}/threads/${encodeURIComponent(threadId)}/history`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  if (response.status === 404) return [];
  if (!response.ok) {
    throw new Error(`Thread history request failed: ${response.status} ${response.statusText}`);
  }
  return response.json();
}

/** Renames one of the user's own conversations: PATCH /threads/{id}. */
export async function renameThread(threadId: string, title: string): Promise<void> {
  const token = await getValidToken();
  const response = await fetch(`${API_BASE_URL}/threads/${encodeURIComponent(threadId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ title }),
  });
  if (!response.ok) {
    throw new Error(`Thread rename failed: ${response.status} ${response.statusText}`);
  }
}

/** Soft-deletes one of the user's own conversations (undo-able via
 * `restoreThread` until purged): DELETE /threads/{id}. Pass
 * `permanent: true` for the immediate, unrecoverable delete. */
export async function deleteThread(threadId: string, permanent = false): Promise<void> {
  const token = await getValidToken();
  const suffix = permanent ? "?permanent=true" : "";
  const response = await fetch(
    `${API_BASE_URL}/threads/${encodeURIComponent(threadId)}${suffix}`,
    {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    },
  );
  if (!response.ok) {
    throw new Error(`Thread delete failed: ${response.status} ${response.statusText}`);
  }
}

/** Undoes a soft delete: POST /threads/{id}/restore. */
export async function restoreThread(threadId: string): Promise<void> {
  const token = await getValidToken();
  const response = await fetch(
    `${API_BASE_URL}/threads/${encodeURIComponent(threadId)}/restore`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    },
  );
  if (!response.ok) {
    throw new Error(`Thread restore failed: ${response.status} ${response.statusText}`);
  }
}

/** Uploads one attachment to a conversation: POST
 * /threads/{id}/attachments (multipart). The server sniffs the real
 * media type and extracts the content once, at upload time. */
export async function uploadAttachment(threadId: string, file: File | Blob): Promise<AttachmentMeta> {
  const token = await getValidToken();
  const form = new FormData();
  form.append("file", file, file instanceof File ? file.name : "pasted-image.png");
  const response = await fetch(
    `${API_BASE_URL}/threads/${encodeURIComponent(threadId)}/attachments`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: form,
    },
  );
  if (!response.ok) {
    const detail = await response.json().then((b) => b.detail).catch(() => null);
    throw new Error(detail ?? `Upload failed: ${response.status} ${response.statusText}`);
  }
  return response.json();
}

/** Fetches an attachment's bytes (image thumbnails in restored history)
 * as a Blob - needed instead of a plain <img src> because the endpoint
 * requires the Authorization header. */
export async function fetchAttachmentBlob(threadId: string, attachmentId: string): Promise<Blob> {
  const token = await getValidToken();
  const response = await fetch(
    `${API_BASE_URL}/threads/${encodeURIComponent(threadId)}/attachments/${encodeURIComponent(attachmentId)}`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  if (!response.ok) {
    throw new Error(`Attachment fetch failed: ${response.status} ${response.statusText}`);
  }
  return response.blob();
}

/** Reports an error the ErrorBoundary caught to POST /client-error
 * (which logs it backend-side, Loki-ready - see app/api/main.py).
 * Never throws: error *reporting* failing must not cascade into the
 * already-broken UI. */
export async function reportClientError(report: {
  message: string;
  stack?: string;
  componentStack?: string;
}): Promise<void> {
  try {
    const token = await getValidToken();
    await fetch(`${API_BASE_URL}/client-error`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({
        message: report.message,
        stack: report.stack ?? null,
        component_stack: report.componentStack ?? null,
        url: window.location.href,
      }),
    });
  } catch {
    // Swallowed deliberately - see docstring.
  }
}

// --- Knowledge-base ingestion (chat-ui-plan5.md Phase B) ---

export interface IngestionEvent {
  node: string;
  elapsed_ms: number;
  detail: string;
}

/** One ingested document's registry view - mirrors the backend's
 * KnowledgeDocument model in app/api/main.py. */
export interface KnowledgeDocument {
  document_id: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  version: number;
  status: "processing" | "indexed" | "needs_review" | "failed";
  topic: string | null;
  subtopic: string | null;
  chapters: string[];
  classification_confidence: number | null;
  error: string | null;
  chunk_count: number;
  chunk_ids: string[];
  events: IngestionEvent[];
  created_at: string;
  updated_at: string;
  duplicate: boolean;
  pending?: {
    version: number;
    topic: string | null;
    subtopic: string | null;
    classification_confidence: number | null;
  } | null;
}

async function knowledgeError(response: Response, fallback: string): Promise<Error> {
  const detail = await response
    .json()
    .then((b) => (typeof b.detail === "string" ? b.detail : null))
    .catch(() => null);
  return new Error(detail ?? `${fallback}: ${response.status} ${response.statusText}`);
}

/** Uploads one document into the ingestion pipeline. The response's
 * status is usually still "processing" (ingestion runs as a background
 * task) - poll getKnowledgeDocument until it settles. `duplicate:
 * true` means these exact bytes were already ingested. */
export async function uploadKnowledgeDocument(file: File): Promise<KnowledgeDocument> {
  const token = await getValidToken();
  const form = new FormData();
  form.append("file", file, file.name);
  const response = await fetch(`${API_BASE_URL}/knowledge/documents`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  if (!response.ok) {
    throw await knowledgeError(response, "Upload failed");
  }
  return response.json();
}

export async function listKnowledgeDocuments(): Promise<KnowledgeDocument[]> {
  const token = await getValidToken();
  const response = await fetch(`${API_BASE_URL}/knowledge/documents`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw await knowledgeError(response, "Document list failed");
  }
  return response.json();
}

export async function getKnowledgeDocument(documentId: string): Promise<KnowledgeDocument> {
  const token = await getValidToken();
  const response = await fetch(
    `${API_BASE_URL}/knowledge/documents/${encodeURIComponent(documentId)}`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  if (!response.ok) {
    throw await knowledgeError(response, "Document fetch failed");
  }
  return response.json();
}

export async function reindexKnowledgeDocument(documentId: string): Promise<KnowledgeDocument> {
  const token = await getValidToken();
  const response = await fetch(
    `${API_BASE_URL}/knowledge/documents/${encodeURIComponent(documentId)}/reindex`,
    { method: "POST", headers: { Authorization: `Bearer ${token}` } },
  );
  if (!response.ok) {
    throw await knowledgeError(response, "Re-index failed");
  }
  return response.json();
}

/** The topic -> subtopics taxonomy documents can be classified into
 * (served by the backend so the override form never drifts from
 * app/config.py's TOPIC_SUBTOPICS). */
export async function fetchKnowledgeTaxonomy(): Promise<Record<string, string[]>> {
  const token = await getValidToken();
  const response = await fetch(`${API_BASE_URL}/knowledge/taxonomy`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw await knowledgeError(response, "Taxonomy fetch failed");
  }
  return response.json();
}

/** Manually (re)classifies a document - the human-in-the-loop fix for
 * needs_review documents. Re-runs ingestion with the chosen taxonomy,
 * so the returned document is back in "processing". */
export async function overrideClassification(
  documentId: string,
  topic: string,
  subtopic: string,
  createMissing = false,
): Promise<KnowledgeDocument> {
  const token = await getValidToken();
  const response = await fetch(
    `${API_BASE_URL}/knowledge/documents/${encodeURIComponent(documentId)}/classification`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ topic, subtopic, create_missing: createMissing }),
    },
  );
  if (!response.ok) {
    throw await knowledgeError(response, "Classification override failed");
  }
  return response.json();
}

export async function refreshClassificationSuggestion(documentId: string): Promise<KnowledgeDocument> {
  const token = await getValidToken();
  const response = await fetch(
    `${API_BASE_URL}/knowledge/documents/${encodeURIComponent(documentId)}/suggestion`,
    { method: "POST", headers: { Authorization: `Bearer ${token}` } },
  );
  if (!response.ok) {
    throw await knowledgeError(response, "Suggestion refresh failed");
  }
  return response.json();
}
