/**
 * Typed client for routing_lab3's custom FastAPI backend
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
}

export interface StreamStatusEvent {
  type: "status";
  node: string;
}

export interface StreamAnswerEvent {
  type: "answer";
  final_answer: string;
  routing_summary: RoutingSummary;
}

export type StreamEvent = StreamStatusEvent | StreamAnswerEvent;

/** One synchronous turn: POST /chat, waits for the complete answer. */
export async function sendChatMessage(
  threadId: string,
  message: string,
): Promise<ChatResponse> {
  const token = await getValidToken();
  const response = await fetch(`${API_BASE_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ thread_id: threadId, message }),
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
): Promise<void> {
  const token = await getValidToken();
  const response = await fetch(`${API_BASE_URL}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ thread_id: threadId, message }),
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
        onEvent({ type: "status", node: data.node });
      } else if (eventName === "answer") {
        onEvent({ type: "answer", final_answer: data.final_answer, routing_summary: data.routing_summary });
      }
    }
  }
}
