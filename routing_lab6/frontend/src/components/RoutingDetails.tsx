import type { ReactNode } from "react";

import type { ExecutionStep, HopResult, RoutingSummary, ToolResult } from "../api/client";
import type { SelectedPassage } from "./PassagePreview";

function Badge({ children, tone = "slate" }: { children: ReactNode; tone?: "slate" | "amber" | "green" }) {
  const toneClasses = {
    slate: "bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700",
    amber: "bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-800",
    green: "bg-green-50 text-green-800 border-green-200 dark:bg-green-950 dark:text-green-300 dark:border-green-800",
  }[tone];
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs ${toneClasses}`}>
      {children}
    </span>
  );
}

function RoutingBreadcrumb({ summary }: { summary: RoutingSummary }) {
  return (
    <div className="flex flex-wrap gap-2">
      {summary.topics.map((topic) => {
        const subtopic = summary.subtopics[topic];
        const chapter = summary.chapters[topic];
        const steps = [topic, subtopic, chapter].filter(Boolean);
        return (
          <Badge key={topic}>{steps.join(" \u203a ")}</Badge>
        );
      })}
    </div>
  );
}

function ToolResultCard({ topic, result }: { topic: string; result: ToolResult }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-2 text-xs dark:border-slate-700 dark:bg-slate-900">
      <p className="font-medium text-slate-700 dark:text-slate-300">
        {topic}: used tool <code className="rounded bg-slate-100 px-1 dark:bg-slate-800">{result.tool_name}</code>
      </p>
      <p className="mt-1 text-slate-500 dark:text-slate-400">Input: {result.tool_input}</p>
      {result.output && <p className="mt-1 text-slate-700 dark:text-slate-300">Output: {result.output}</p>}
      {result.error && <p className="mt-1 text-red-600 dark:text-red-400">Error: {result.error}</p>}
    </div>
  );
}

function HopTrace({ hops }: { hops: HopResult[] }) {
  return (
    <ol className="space-y-2">
      {hops.map((hop) => (
        <li key={hop.hop_number} className="rounded-lg border border-slate-200 bg-white p-2 text-xs dark:border-slate-700 dark:bg-slate-900">
          <p className="font-medium text-slate-700 dark:text-slate-300">Hop {hop.hop_number}: {hop.question}</p>
          <p className="mt-1 text-slate-600 dark:text-slate-400">{hop.final_answer}</p>
          {hop.extracted_value && (
            <p className="mt-1 text-slate-500 dark:text-slate-400">Extracted: {hop.extracted_value}</p>
          )}
        </li>
      ))}
    </ol>
  );
}

function formatMs(ms: number): string {
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

/** The node-by-node execution timeline with per-node durations - the
 * first slice of chat-ui-plan2.md §3's "LangGraph Inspector", rendered
 * inside the existing per-turn panel rather than a separate sidebar
 * (chat-ui-plan3.md §2.2). */
function ExecutionTimeline({ steps }: { steps: ExecutionStep[] }) {
  const totalMs = steps.reduce((sum, step) => sum + (step.elapsedMs ?? 0), 0);
  return (
    <div>
      <p className="font-medium text-slate-600 dark:text-slate-300">Execution</p>
      <ol className="mt-1 space-y-0.5 font-mono text-[11px]">
        {steps.map((step, index) => (
          <li key={index} className="flex justify-between gap-3">
            <span>{step.node}</span>
            {step.elapsedMs != null && (
              <span className="text-slate-400 dark:text-slate-500">{formatMs(step.elapsedMs)}</span>
            )}
          </li>
        ))}
        <li className="flex justify-between gap-3 border-t border-slate-200 pt-0.5 dark:border-slate-700">
          <span>total</span>
          <span>{formatMs(totalMs)}</span>
        </li>
      </ol>
    </div>
  );
}

/**
 * Collapsible per-turn panel rendering `routing_summary` (see
 * app/chat/routing_summary.py): the topic/subtopic/chapter routing
 * trail, any tool that ran, the multi-hop trace when present, the
 * retrieved passages (citations) that grounded the answer, and - for
 * live-streamed turns - the node execution timeline. Each cited
 * passage card is clickable, opening the full passage in the
 * PassagePreview panel (a separate citation-chips row above this panel
 * was tried first and removed as duplicative, per user feedback).
 * Renders nothing if there's neither topic data nor a trace (e.g. a
 * restored conversation-meta turn).
 */
export function RoutingDetails({
  summary,
  executionTrace,
  onOpenPassage,
}: {
  summary: RoutingSummary;
  executionTrace?: ExecutionStep[];
  onOpenPassage?: (passage: SelectedPassage) => void;
}) {
  const hasTrace = (executionTrace?.length ?? 0) > 0;
  if (summary.topics.length === 0 && !hasTrace) return null;

  const toolEntries = Object.entries(summary.tool_results);
  const recoveredTopics = Object.entries(summary.recovery_attempts).filter(
    ([, attempt]) => attempt.attempted,
  );

  return (
    <details className="mt-1 text-xs text-slate-500 dark:text-slate-400">
      <summary className="cursor-pointer select-none">Routing details</summary>
      <div className="mt-2 space-y-3 rounded-lg bg-slate-50 p-3 dark:bg-slate-800">
        <RoutingBreadcrumb summary={summary} />
        {hasTrace && executionTrace && <ExecutionTimeline steps={executionTrace} />}
        {recoveredTopics.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {recoveredTopics.map(([topic, attempt]) => (
              <Badge key={topic} tone={attempt.succeeded ? "green" : "amber"}>
                {topic}: retried ({attempt.reason}){attempt.succeeded ? " - recovered" : ""}
              </Badge>
            ))}
          </div>
        )}

        {summary.is_multi_hop && summary.hop_results.length > 0 && (
          <HopTrace hops={summary.hop_results} />
        )}

        {toolEntries.length > 0 && (
          <div className="space-y-2">
            {toolEntries.map(([topic, result]) => (
              <ToolResultCard key={topic} topic={topic} result={result} />
            ))}
          </div>
        )}

        {Object.entries(summary.passages).map(([topic, passages]) =>
          passages.length > 0 ? (
            <div key={topic} className="space-y-1.5">
              <p className="font-medium text-slate-600 dark:text-slate-300">{topic} retrieved passages (not verified citations)</p>
              {passages.map((passage, index) => (
                <button
                  key={index}
                  type="button"
                  onClick={() => onOpenPassage?.({ ...passage, topic })}
                  className="block w-full rounded-lg border border-slate-200 bg-white p-2 text-left hover:border-slate-400 dark:border-slate-700 dark:bg-slate-900 dark:hover:border-slate-500"
                >
                  <p className="font-medium text-slate-600 dark:text-slate-300">
                    {passage.chapter_id}
                    {passage.source && ` · ${passage.source}`}
                    {passage.page != null && ` · page ${passage.page}`}
                    {passage.version != null && ` · v${passage.version}`}
                    {passage.score != null && ` (score ${passage.score.toFixed(2)})`}
                  </p>
                  {passage.text && <p className="mt-1 text-slate-500 dark:text-slate-400">{passage.text.slice(0, 220)}{passage.text.length > 220 ? "…" : ""}</p>}
                </button>
              ))}
            </div>
          ) : null,
        )}
      </div>
    </details>
  );
}
