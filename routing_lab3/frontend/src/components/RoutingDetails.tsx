import type { ReactNode } from "react";

import type { HopResult, RoutingSummary, ToolResult } from "../api/client";

function Badge({ children, tone = "slate" }: { children: ReactNode; tone?: "slate" | "amber" | "green" }) {
  const toneClasses = {
    slate: "bg-slate-100 text-slate-700 border-slate-200",
    amber: "bg-amber-50 text-amber-800 border-amber-200",
    green: "bg-green-50 text-green-800 border-green-200",
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
    <div className="rounded-lg border border-slate-200 bg-white p-2 text-xs">
      <p className="font-medium text-slate-700">
        {topic}: used tool <code className="rounded bg-slate-100 px-1">{result.tool_name}</code>
      </p>
      <p className="mt-1 text-slate-500">Input: {result.tool_input}</p>
      {result.output && <p className="mt-1 text-slate-700">Output: {result.output}</p>}
      {result.error && <p className="mt-1 text-red-600">Error: {result.error}</p>}
    </div>
  );
}

function HopTrace({ hops }: { hops: HopResult[] }) {
  return (
    <ol className="space-y-2">
      {hops.map((hop) => (
        <li key={hop.hop_number} className="rounded-lg border border-slate-200 bg-white p-2 text-xs">
          <p className="font-medium text-slate-700">Hop {hop.hop_number}: {hop.question}</p>
          <p className="mt-1 text-slate-600">{hop.final_answer}</p>
          {hop.extracted_value && (
            <p className="mt-1 text-slate-500">Extracted: {hop.extracted_value}</p>
          )}
        </li>
      ))}
    </ol>
  );
}

/**
 * Collapsible per-turn panel rendering `routing_summary` (see
 * app/chat/routing_summary.py): the topic/subtopic/chapter routing
 * trail, any tool that ran, the multi-hop trace when present, and the
 * retrieved passages (citations) that grounded the answer. Renders
 * nothing if there's no topic data at all (e.g. a turn that errored
 * before routing ran).
 */
export function RoutingDetails({ summary }: { summary: RoutingSummary }) {
  if (summary.topics.length === 0) return null;

  const toolEntries = Object.entries(summary.tool_results);
  const recoveredTopics = Object.entries(summary.recovery_attempts).filter(
    ([, attempt]) => attempt.attempted,
  );

  return (
    <details className="mt-1 text-xs text-slate-500">
      <summary className="cursor-pointer select-none">Routing details</summary>
      <div className="mt-2 space-y-3 rounded-lg bg-slate-50 p-3">
        <RoutingBreadcrumb summary={summary} />

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
              <p className="font-medium text-slate-600">{topic} sources</p>
              {passages.map((passage, index) => (
                <div key={index} className="rounded-lg border border-slate-200 bg-white p-2">
                  <p className="font-medium text-slate-600">
                    {passage.chapter_id}
                    {passage.score != null && ` (score ${passage.score.toFixed(2)})`}
                  </p>
                  {passage.text && <p className="mt-1 text-slate-500">{passage.text.slice(0, 220)}{passage.text.length > 220 ? "…" : ""}</p>}
                </div>
              ))}
            </div>
          ) : null,
        )}
      </div>
    </details>
  );
}
