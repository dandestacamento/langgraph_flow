"""Exports MLflow traces from the `langgraph_routing_lab` experiment to a
local JSON file, so a question's full routing decisions, execution trace,
final answer, and token/cost usage can be inspected directly (e.g. by an
AI assistant reading the file) without needing to open the MLflow UI or
take screenshots of it.

MLflow's `mlflow.langchain.autolog()` (enabled by
`app.observability.mlflow_tracing.enable_mlflow_tracing_if_available`)
captures the LangGraph root span's input/output automatically - the
"output" is the *entire* final `RoutingState` dict (final_answer, every
router's decision, the full execution_log, retrieved passages, etc.),
since that's exactly what `graph.invoke()` returns. This script reads
that root span's output back out via `mlflow.search_traces()` rather than
re-deriving anything, so the exported file is a 1:1 reflection of what
actually happened, not a re-summary.

Requires the MLflow tracking server to be running (see start_mlflow.ps1)
and at least one question to have already been asked through the
dashboard, CLI, or test suite while tracing was active.

Usage:
    python scripts/export_mlflow_traces.py
    python scripts/export_mlflow_traces.py --limit 5 --output experiments/mlflow_export.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.observability.mlflow_tracing import DEFAULT_TRACKING_URI, EXPERIMENT_NAME  # noqa: E402

DEFAULT_OUTPUT = PROJECT_ROOT / "experiments" / "mlflow_trace_export.json"


def export_traces(limit: int, tracking_uri: str, experiment_name: str) -> list[dict]:
    import mlflow

    mlflow.set_tracking_uri(tracking_uri)
    experiment = mlflow.get_experiment_by_name(experiment_name)
    if experiment is None:
        raise RuntimeError(
            f"No MLflow experiment named {experiment_name!r} found at {tracking_uri} - "
            "ask at least one question through the dashboard/CLI while MLflow tracing is "
            "active (see start_mlflow.ps1) before running this script."
        )

    traces_df = mlflow.search_traces(
        locations=[experiment.experiment_id],
        max_results=limit,
        order_by=["timestamp_ms DESC"],
    )

    exported = []
    for _, row in traces_df.iterrows():
        response = row["response"] or {}
        metadata = row["trace_metadata"] or {}
        token_usage = json.loads(metadata["mlflow.trace.tokenUsage"]) if "mlflow.trace.tokenUsage" in metadata else None
        cost = json.loads(metadata["mlflow.trace.cost"]) if "mlflow.trace.cost" in metadata else None

        exported.append(
            {
                "trace_id": row["trace_id"],
                "state": row["state"],
                "request_time_ms": row["request_time"],
                "execution_duration_ms": row["execution_duration"],
                "question": response.get("question"),
                "final_answer": response.get("final_answer"),
                "selected_topics": response.get("selected_topics"),
                "selected_subtopics": response.get("selected_subtopics"),
                "selected_chapters": response.get("selected_chapters"),
                "is_ambiguous": (response.get("topic_decision") or {}).get("is_ambiguous"),
                "is_multi_hop": response.get("is_multi_hop"),
                "tool_decisions": response.get("tool_decisions"),
                "recovery_attempts": response.get("recovery_attempts"),
                "retrieved_chapters_by_topic": {
                    topic: [p["chapter_id"] for p in passages]
                    for topic, passages in (response.get("retrieved_passages") or {}).items()
                },
                "execution_log": response.get("execution_log"),
                "token_usage": token_usage,
                "cost_usd": cost,
            }
        )
    return exported


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=20, help="Max number of recent traces to export.")
    parser.add_argument("--output", type=str, default=str(DEFAULT_OUTPUT), help="Output JSON file path.")
    parser.add_argument("--tracking-uri", type=str, default=DEFAULT_TRACKING_URI)
    parser.add_argument("--experiment", type=str, default=EXPERIMENT_NAME)
    args = parser.parse_args()

    exported = export_traces(args.limit, args.tracking_uri, args.experiment)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(exported, indent=2), encoding="utf-8")

    print(f"Exported {len(exported)} trace(s) to {output_path}")
    for t in exported:
        print(f"  - [{t['state']}] {t['question']!r} -> {(t['final_answer'] or '')[:80]!r}")


if __name__ == "__main__":
    main()
