"""Batch Routing Test Runner (instructions/Langgraph_routing/9_batch_routing.md).

Runs every question in datasets/batch_test_questions.json through the
full compiled graph (`app.graph.build_graph()` - the exact same graph
`app.main` and the pytest suite use) and writes four reports to
outputs/:

- batch_results.csv   - one row per test: pass/fail + timing/cost, for a
  quick spreadsheet scan.
- batch_details.json  - the full routing chain, retrieved chapters, tool
  calls, final answer, and execution trace for every test.
- batch_report.md     - a readable Markdown report, one section per
  question, in the same "expected / routing chain / answer" style as
  experiments/sample_questions_report.md.
- manual_review.csv   - your own verdict/comments column, preserved
  across reruns by test_id (see merge_manual_review below) so
  re-running the suite after a fix never overwrites your notes.

Each question is scored on exactly the routing dimensions listed in its
own "graded" field (topic/subtopic/chapter/chapters/tool/behavior/
multihop/recovery) - mirroring how each level's own pytest file
(tests/test_*_routing.py etc.) only grades the dimensions that level
actually introduces. Routing correctness and answer correctness are
always reported as two separate fields, never conflated into one score -
see app/evaluation/routing_metrics.py and app/evaluation/answer_metrics.py,
and instructions/Langgraph_routing/4_to_5_obserability.md for why.

The compiled graph has no checkpointer, so graph.invoke() is already
fully stateless between questions - no conversation memory can leak
between test cases, and no thread_id is needed to guarantee that.

If a question's invocation raises (an actual bug, not a wrong answer),
that test is recorded with its real error message and scored as
incorrect - never silently skipped or marked as a fabricated pass.

Usage:
    python scripts/run_batch_tests.py
    python scripts/run_batch_tests.py --ids T001 T015 T020
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import warnings
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import find_dotenv, load_dotenv  # noqa: E402

load_dotenv(find_dotenv())

from app.cache import enable_llm_cache  # noqa: E402
from app.evaluation.answer_metrics import AnswerResult  # noqa: E402
from app.evaluation.retrieval_metrics import MultiChapterRetrievalResult  # noqa: E402
from app.evaluation.routing_metrics import (  # noqa: E402
    ChapterRoutingResult,
    ClarificationResult,
    MultiHopResult,
    RecoveryResult,
    RoutingResult,
    SubtopicRoutingResult,
    ToolSelectionResult,
)
from app.graph import build_graph  # noqa: E402
from app.observability.execution_logger import get_node_sequence  # noqa: E402
from app.observability.graph_visualizer import render_graph_diagram  # noqa: E402
from app.observability.mlflow_tracing import enable_mlflow_tracing_if_available  # noqa: E402
from app.state import initial_state  # noqa: E402

DATASET_PATH = PROJECT_ROOT / "datasets" / "batch_test_questions.json"
OUTPUT_DIR = PROJECT_ROOT / "outputs"
MANUAL_REVIEW_FIELDS = ["test_id", "level", "question", "answer_verdict", "route_verdict", "comments"]
RESULTS_FIELDS = [
    "test_id", "level", "question", "routing_correct", "answer_correct",
    "overall_correct", "latency_ms", "total_tokens", "cost_usd", "error",
]


def load_questions(path: Path, ids: list[str] | None = None) -> list[dict]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if ids:
        wanted = set(ids)
        cases = [c for c in cases if c["test_id"] in wanted]
        missing = wanted - {c["test_id"] for c in cases}
        if missing:
            raise SystemExit(f"Unknown test_id(s) in {path}: {sorted(missing)}")
    return cases


def _hop1_value(output: dict) -> str | None:
    hop_results = output.get("hop_results") or []
    return hop_results[0]["extracted_value"] if hop_results else None


def _actual_behavior(output: dict) -> str:
    return "clarify" if "clarification_agent" in get_node_sequence(output.get("execution_log", [])) else "answer"


def score_case(case: dict, output: dict) -> dict:
    """Scores exactly the dimensions listed in case["graded"], reusing
    the same dataclasses the per-level pytest files use - see that
    field's values in datasets/batch_test_questions.json for which
    dimensions apply to which level."""
    graded = case.get("graded", [])
    scores: dict = {}
    expected_topics = case.get("expected_topics")
    expected_topic = expected_topics[0] if expected_topics else None

    if "topic" in graded:
        result = RoutingResult(
            question_id=case["test_id"],
            expected_topics=expected_topics or [],
            actual_topics=output.get("selected_topics") or [],
        )
        scores["topic_correct"] = result.is_correct

    if "subtopic" in graded:
        result = SubtopicRoutingResult(
            question_id=case["test_id"],
            expected_topic=expected_topic,
            expected_subtopic=case["expected_subtopic"],
            actual_topics=output.get("selected_topics") or [],
            actual_subtopics=output.get("selected_subtopics") or {},
        )
        scores["subtopic_correct"] = result.is_correct

    if "chapter" in graded:
        result = ChapterRoutingResult(
            question_id=case["test_id"],
            expected_topic=expected_topic,
            expected_subtopic=case["expected_subtopic"],
            expected_chapter=case["expected_chapter"],
            actual_topics=output.get("selected_topics") or [],
            actual_subtopics=output.get("selected_subtopics") or {},
            actual_chapters=output.get("selected_chapters") or {},
        )
        scores["chapter_correct"] = result.is_correct

    if "chapters" in graded:
        retrieved = output.get("retrieved_passages", {}).get(expected_topic, [])
        result = MultiChapterRetrievalResult(
            question_id=case["test_id"],
            expected_chapters=case["expected_chapters"],
            retrieved_chapter_ids=[p["chapter_id"] for p in retrieved],
        )
        scores["chapters_correct"] = result.is_fully_covered
        scores["chapters_coverage"] = round(result.coverage_fraction, 4)

    if "tool" in graded:
        decision = output.get("tool_decisions", {}).get(expected_topic, {})
        result = ToolSelectionResult(
            question_id=case["test_id"],
            expected_tool=case["expected_tool"],
            actual_needs_tool=decision.get("needs_tool", False),
            actual_tool=decision.get("tool_name"),
        )
        scores["tool_correct"] = result.is_correct

    if "behavior" in graded:
        result = ClarificationResult(
            question_id=case["test_id"],
            expected_behavior=case["expected_behavior"],
            actual_behavior=_actual_behavior(output),
        )
        scores["behavior_correct"] = result.is_correct

    if "multihop" in graded:
        result = MultiHopResult(
            question_id=case["test_id"],
            expected_is_multi_hop=case["expected_is_multi_hop"],
            expected_hop1_fact=case.get("expected_hop1_fact"),
            actual_is_multi_hop=output.get("is_multi_hop", False),
            actual_hop1_value=_hop1_value(output),
        )
        scores["multihop_correct"] = result.is_correct

    if "recovery" in graded:
        recovery = output.get("recovery_attempts", {}).get(expected_topic, {})
        result = RecoveryResult(
            question_id=case["test_id"],
            expected_recovery_attempted=case["expected_recovery_attempted"],
            actual_recovery_attempted=recovery.get("attempted", False),
        )
        scores["recovery_correct"] = result.is_correct

    routing_dims = [v for k, v in scores.items() if k.endswith("_correct")]
    scores["routing_correct"] = all(routing_dims) if routing_dims else None

    if case.get("score_answer", True):
        is_answerable = case.get("is_answerable")
        if is_answerable is None:
            is_answerable = True
        final_answer = output.get("final_answer", "")
        retrieved_texts = [
            p["text"]
            for topic_passages in (output.get("retrieved_passages") or {}).values()
            for p in topic_passages
        ]
        answer_result = AnswerResult(
            question_id=case["test_id"],
            actual_answer=final_answer,
            expected_facts=case.get("expected_facts") or [],
            retrieved_texts=retrieved_texts,
            is_answerable=is_answerable,
        )
        scores["answer_correct"] = answer_result.is_correct
        scores["answer_correctness"] = round(answer_result.correctness, 4)
        scores["groundedness"] = round(answer_result.groundedness_score, 4)
    else:
        scores["answer_correct"] = None
        scores["answer_correctness"] = None
        scores["groundedness"] = None

    overall_dims = [d for d in (scores["routing_correct"], scores["answer_correct"]) if d is not None]
    scores["overall_correct"] = all(overall_dims) if overall_dims else None
    return scores


def run_case(graph, case: dict) -> dict:
    """Invokes the graph for one question, capturing latency, token
    usage/cost (via LangChain's OpenAI callback), and the MLflow trace id
    (if tracing is active) - or the real error message if invocation
    itself raised, rather than fabricating a result."""
    from langchain_community.callbacks import get_openai_callback

    error: str | None = None
    output: dict = {}
    trace_id: str | None = None
    usage = {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}

    start = time.perf_counter()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # cosmetic: langchain-community sunset notice
            with get_openai_callback() as cb:
                output = graph.invoke(initial_state(case["question"]))
            usage = {
                "total_tokens": cb.total_tokens,
                "prompt_tokens": cb.prompt_tokens,
                "completion_tokens": cb.completion_tokens,
                "cost_usd": round(cb.total_cost, 6),
            }
        try:
            import mlflow

            trace_id = mlflow.get_last_active_trace_id()
        except Exception:
            trace_id = None
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    latency_ms = round((time.perf_counter() - start) * 1000, 1)

    return {"output": output, "error": error, "latency_ms": latency_ms, "trace_id": trace_id, **usage}


def build_detail(case: dict, run_result: dict, scores: dict) -> dict:
    output = run_result["output"]
    retrieved_by_topic = {
        topic: [p["chapter_id"] for p in passages]
        for topic, passages in (output.get("retrieved_passages") or {}).items()
    }
    return {
        "test_id": case["test_id"],
        "level": case["level"],
        "question": case["question"],
        "notes": case.get("notes", ""),
        "expected": {
            "topics": case.get("expected_topics"),
            "subtopic": case.get("expected_subtopic"),
            "chapter": case.get("expected_chapter"),
            "chapters": case.get("expected_chapters"),
            "tool": case.get("expected_tool"),
            "behavior": case.get("expected_behavior"),
            "is_multi_hop": case.get("expected_is_multi_hop"),
            "hop1_fact": case.get("expected_hop1_fact"),
            "recovery_attempted": case.get("expected_recovery_attempted"),
            "is_answerable": case.get("is_answerable"),
            "facts": case.get("expected_facts"),
            "answer": case.get("expected_answer"),
        },
        "actual": {
            "node_sequence": get_node_sequence(output.get("execution_log", [])),
            "selected_topics": output.get("selected_topics"),
            "selected_subtopics": output.get("selected_subtopics"),
            "selected_chapters": output.get("selected_chapters"),
            "retrieved_chapters_by_topic": retrieved_by_topic,
            "tool_decisions": output.get("tool_decisions"),
            "tool_results": output.get("tool_results"),
            "is_multi_hop": output.get("is_multi_hop"),
            "hop_results": output.get("hop_results"),
            "recovery_attempts": output.get("recovery_attempts"),
            "final_answer": output.get("final_answer"),
            "execution_log": output.get("execution_log"),
        },
        "scores": scores,
        "mlflow_trace_id": run_result["trace_id"],
        "latency_ms": run_result["latency_ms"],
        "total_tokens": run_result["total_tokens"],
        "prompt_tokens": run_result["prompt_tokens"],
        "completion_tokens": run_result["completion_tokens"],
        "cost_usd": run_result["cost_usd"],
        "error": run_result["error"],
    }


def write_results_csv(path: Path, details: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RESULTS_FIELDS)
        writer.writeheader()
        for d in details:
            writer.writerow(
                {
                    "test_id": d["test_id"],
                    "level": d["level"],
                    "question": d["question"],
                    "routing_correct": d["scores"].get("routing_correct"),
                    "answer_correct": d["scores"].get("answer_correct"),
                    "overall_correct": d["scores"].get("overall_correct"),
                    "latency_ms": d["latency_ms"],
                    "total_tokens": d["total_tokens"],
                    "cost_usd": d["cost_usd"],
                    "error": d["error"] or "",
                }
            )


def merge_manual_review(path: Path, cases: list[dict]) -> list[dict]:
    """Preserves your `answer_verdict`/`route_verdict`/`comments` across
    reruns, keyed by test_id - a rerun only ever refreshes the
    level/question text, never your own notes. Rows for a test_id that
    existed in a prior run but isn't in this run's `cases` (e.g. a
    one-off `--ids` filter) are kept untouched rather than dropped."""
    existing: dict[str, dict] = {}
    if path.exists():
        with path.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                existing[row["test_id"]] = row

    merged = []
    seen_ids = set()
    for case in cases:
        prior = existing.get(case["test_id"], {})
        merged.append(
            {
                "test_id": case["test_id"],
                "level": case["level"],
                "question": case["question"],
                "answer_verdict": prior.get("answer_verdict", ""),
                "route_verdict": prior.get("route_verdict", ""),
                "comments": prior.get("comments", ""),
            }
        )
        seen_ids.add(case["test_id"])

    for test_id, row in existing.items():
        if test_id not in seen_ids:
            merged.append(row)
    return merged


def write_manual_review_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANUAL_REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _fmt(value) -> str:
    return "—" if value in (None, [], "") else str(value)


def _bool_icon(value: bool | None) -> str:
    if value is None:
        return "n/a"
    return "correct" if value else "WRONG"


def render_markdown_report(details: list[dict]) -> str:
    total = len(details)
    routing_dims = [d["scores"]["routing_correct"] for d in details if d["scores"].get("routing_correct") is not None]
    answer_dims = [d["scores"]["answer_correct"] for d in details if d["scores"].get("answer_correct") is not None]
    overall_dims = [d["scores"]["overall_correct"] for d in details if d["scores"].get("overall_correct") is not None]
    errors = [d for d in details if d["error"]]
    total_tokens = sum(d["total_tokens"] for d in details)
    total_cost = sum(d["cost_usd"] for d in details)
    total_latency_s = sum(d["latency_ms"] for d in details) / 1000

    lines: list[str] = ["# Batch Routing Test Report", ""]
    lines.append(
        "Generated by `scripts/run_batch_tests.py` from `datasets/batch_test_questions.json` "
        f"({total} questions)."
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **{total}** questions tested")
    if routing_dims:
        lines.append(f"- **{sum(routing_dims)}/{len(routing_dims)}** correct routing decisions")
    if answer_dims:
        lines.append(f"- **{sum(answer_dims)}/{len(answer_dims)}** correct answers")
    if overall_dims:
        lines.append(f"- **{sum(overall_dims)}/{len(overall_dims)}** fully correct (routing AND answer)")
    if errors:
        lines.append(f"- **{len(errors)}** execution error(s)")
    lines.append(f"- Totals: {total_tokens} tokens, ${total_cost:.5f}, {total_latency_s:.2f}s combined latency")
    lines.append("")
    lines.append("| # | Test | Level | Question | Routing | Answer | Overall | Cost |")
    lines.append("|---|------|-------|----------|---------|--------|---------|------|")
    for i, d in enumerate(details, start=1):
        q = d["question"].replace("|", "\\|")
        q_short = q if len(q) <= 60 else q[:57] + "..."
        lines.append(
            f"| {i} | {d['test_id']} | {d['level']} | {q_short} | "
            f"{_bool_icon(d['scores'].get('routing_correct'))} | {_bool_icon(d['scores'].get('answer_correct'))} | "
            f"{_bool_icon(d['scores'].get('overall_correct'))} | ${d['cost_usd']:.5f} |"
        )

    lines.append("")
    lines.append("## Per-question detail")
    for d in details:
        lines.append("")
        lines.append(f"### {d['test_id']} (Level {d['level']}) - \"{d['question']}\"")
        lines.append("")
        if d["notes"]:
            lines.append(f"*{d['notes']}*")
            lines.append("")
        if d["error"]:
            lines.append(f"**Execution error:** `{d['error']}`")
            lines.append("")
            continue

        exp, act = d["expected"], d["actual"]
        lines.append(
            f"**Expected:** topics={_fmt(exp['topics'])}, subtopic={_fmt(exp['subtopic'])}, "
            f"chapter={_fmt(exp['chapter'] or exp['chapters'])}, tool={_fmt(exp['tool'])}, "
            f"behavior={_fmt(exp['behavior'])}, facts={_fmt(exp['facts'])}"
        )
        lines.append("")
        lines.append(f"**Expected answer:** {_fmt(exp['answer'])}")
        lines.append("")
        lines.append(f"**Routing chain:** {' -> '.join(act['node_sequence']) or '(none)'}")
        lines.append("")
        lines.append(
            f"**Actual:** topics={_fmt(act['selected_topics'])}, subtopics={_fmt(act['selected_subtopics'])}, "
            f"chapters={_fmt(act['selected_chapters'])}, retrieved_chapters={_fmt(act['retrieved_chapters_by_topic'])}"
        )
        lines.append("")
        if act.get("tool_decisions"):
            lines.append(f"**Tool decisions:** {act['tool_decisions']}")
            lines.append("")
        if act.get("is_multi_hop"):
            lines.append(f"**Multi-hop:** {act['hop_results']}")
            lines.append("")
        if act.get("recovery_attempts"):
            lines.append(f"**Recovery attempts:** {act['recovery_attempts']}")
            lines.append("")
        lines.append(f"**Actual answer:** {act['final_answer']}")
        lines.append("")
        score_bits = ", ".join(f"{k}={v}" for k, v in d["scores"].items())
        lines.append(f"**Automated scores:** {score_bits}")
        lines.append("")
        lines.append(
            f"**Your manual review:** edit the `{d['test_id']}` row in `outputs/manual_review.csv` "
            "(answer_verdict / route_verdict / comments)."
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", nargs="+", default=None, help="Run only these test_id(s), e.g. --ids T001 T015")
    parser.add_argument("--dataset", type=str, default=str(DATASET_PATH), help="Path to the editable question dataset JSON.")
    parser.add_argument("--output-dir", type=str, default=str(OUTPUT_DIR), help="Directory for generated reports.")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if enable_llm_cache():
        print("(LLM/embedding response cache active - see app/cache.py)")
    if enable_mlflow_tracing_if_available():
        print("(MLflow tracing active - see http://127.0.0.1:5000)")
    else:
        print("(MLflow NOT reachable - these runs will not be traced; run ..\\start_mlflow.ps1 first for traces)")

    cases = load_questions(dataset_path, args.ids)
    print(f"\nRunning {len(cases)} test question(s) through the full graph...\n")

    graph = build_graph()

    try:
        _, mermaid_source = render_graph_diagram(graph)
        (output_dir / "routing_graph.mmd").write_text(mermaid_source, encoding="utf-8")
    except Exception as exc:
        print(f"(Could not render routing_graph.mmd: {exc})")

    details = []
    for i, case in enumerate(cases, start=1):
        print(f"[{i}/{len(cases)}] {case['test_id']} (L{case['level']}): {case['question'][:80]}")
        run_result = run_case(graph, case)
        if run_result["error"]:
            scores = {"routing_correct": False, "answer_correct": False, "overall_correct": False}
            print(f"    ERROR: {run_result['error']}")
        else:
            scores = score_case(case, run_result["output"])
            print(
                f"    routing={scores.get('routing_correct')} answer={scores.get('answer_correct')} "
                f"overall={scores.get('overall_correct')}"
            )
        details.append(build_detail(case, run_result, scores))

    write_results_csv(output_dir / "batch_results.csv", details)
    (output_dir / "batch_details.json").write_text(json.dumps(details, indent=2, default=str), encoding="utf-8")
    (output_dir / "batch_report.md").write_text(render_markdown_report(details), encoding="utf-8")
    merged_review = merge_manual_review(output_dir / "manual_review.csv", cases)
    write_manual_review_csv(output_dir / "manual_review.csv", merged_review)

    print(
        f"\nWrote reports to {output_dir}\\ "
        "(batch_results.csv, batch_details.json, batch_report.md, manual_review.csv, routing_graph.mmd)"
    )


if __name__ == "__main__":
    main()
