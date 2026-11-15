"""Compares three routing architectures on the same test set, per the
"advanced experiment" in
instructions/Langgraph_routing/6_routing_design.md:

    Architecture A - LLM Router: LLM selects one topic and agent.
    Architecture B - Hierarchical Router: Topic -> subtopic -> chapter -> retrieval.
    Architecture C - Hybrid Router: LLM + semantic search + multi-agent planning + validation.

A and B are the new, deliberately-simpler graphs in `app.architectures`
(see that package's docstring for what each one does and doesn't do). C
is `app.graph.build_graph()`, completely unchanged - the full 10-level
pipeline this project has built.

Rather than running the entire 228-row dataset (expensive for Architecture
A, which has its own fresh, uncached prompt), this runs a stratified
sample: every Level 1-4 question is grouped by its expected topic (and,
for Level 4, by answerable/unanswerable) and up to `CORE_PER_GROUP` rows
per group are kept, since these are the levels all three architectures
can meaningfully attempt end to end. Levels 5-10 are added as a smaller
"stress sample" (up to `STRESS_PER_GROUP` rows per group, grouped by
topic-set) specifically because Architectures A and B structurally lack
the mechanisms (clarification, multi-topic planning, tool selection,
multi-hop decomposition, error recovery) those levels test - the
experiment's whole point is to see whether C's added complexity earns
its cost on exactly these questions, not just on the easy ones every
architecture can already handle.

Usage:
    python scripts/compare_architectures.py
    python scripts/compare_architectures.py --save experiments/architecture_comparison_results.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import find_dotenv, load_dotenv  # noqa: E402

load_dotenv(find_dotenv())

from app.agents._shared import INSUFFICIENT_INFO_MARKER  # noqa: E402
from app.architectures.arch_a_llm_router import build_arch_a_graph  # noqa: E402
from app.architectures.arch_b_hierarchical_router import build_arch_b_graph  # noqa: E402
from app.cache import enable_llm_cache  # noqa: E402
from app.evaluation.answer_metrics import AnswerResult  # noqa: E402
from app.evaluation.routing_metrics import RoutingResult  # noqa: E402
from app.graph import build_graph  # noqa: E402
from app.observability.execution_logger import get_node_sequence  # noqa: E402
from app.state import initial_state  # noqa: E402

enable_llm_cache()

GROUND_TRUTH_PATH = PROJECT_ROOT / "datasets" / "routing_ground_truth.jsonl"

CORE_LEVELS = {1, 2, 3, 4}
STRESS_LEVELS = {5, 6, 7, 8, 9, 10}
CORE_PER_GROUP = 1
STRESS_PER_GROUP = 1

ARCHITECTURES = {
    "A (LLM Router)": build_arch_a_graph,
    "B (Hierarchical Router)": build_arch_b_graph,
    "C (Hybrid Router)": build_graph,
}


def load_ground_truth() -> list[dict]:
    rows = []
    with GROUND_TRUTH_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _group_key(row: dict) -> tuple:
    """Groups rows so the sample stays topic-diverse and
    answerable/unanswerable-diverse, rather than clustering on whichever
    topic happens to have the most rows in a level. Level 9 rows have no
    `expected_topics` field at all (see README's Level 9 backfill note),
    so they're grouped by `expected_is_multi_hop` instead, to get a mix
    of genuine multi-hop cases and single-hop regression checks rather
    than everything collapsing into one undifferentiated group."""
    if row["level"] == 9:
        return (row.get("expected_is_multi_hop"),)
    topics = tuple(sorted(row.get("expected_topics", []))) or ("?",)
    if row["level"] == 4:
        return (topics, row.get("is_answerable", True))
    return (topics,)


def select_sample() -> list[dict]:
    """Stratified sample: up to CORE_PER_GROUP rows per (level, topic-key)
    group for Levels 1-4, up to STRESS_PER_GROUP for Levels 5-10."""
    all_rows = load_ground_truth()
    by_level: dict[int, list[dict]] = defaultdict(list)
    for row in all_rows:
        by_level[row["level"]].append(row)

    sample: list[dict] = []
    for level, rows in sorted(by_level.items()):
        if level in CORE_LEVELS:
            cap = CORE_PER_GROUP
        elif level in STRESS_LEVELS:
            cap = STRESS_PER_GROUP
        else:
            continue
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for row in rows:
            groups[_group_key(row)].append(row)
        for group_rows in groups.values():
            sample.extend(group_rows[:cap])
    return sample


def count_llm_calls(execution_log: list[dict]) -> int:
    """Cost proxy: number of execution_log entries that represent a real
    LLM call. Any node whose name contains "retriever" (`rag_retriever`,
    Architecture A's `arch_a_retriever`, or their `hop1:`/`hop2:`-prefixed
    forms from a multi-hop sub-invocation) is a vector-embedding call, not
    an LLM chat completion, and is excluded - embeddings are a different,
    much cheaper API call, and conflating the two would overstate the
    cheaper architectures' true LLM cost. A `duration_ms == 0.0` entry is
    a documented free pass-through (e.g. `synthesis_agent` for a
    single-topic question, or `multihop_agent`'s own bookkeeping entries -
    the hop sub-invocations' real calls are counted via their own
    propagated, `hopN:`-prefixed entries instead, see
    `app.agents.multihop_agent`)."""
    return sum(
        1
        for entry in execution_log
        if entry.get("duration_ms", 0.0) > 0.0 and "retriever" not in entry["node"]
    )


def invoke_and_measure(graph, question: str) -> tuple[dict, float, int]:
    start = time.perf_counter()
    output = graph.invoke(initial_state(question))
    latency_ms = (time.perf_counter() - start) * 1000
    llm_calls = count_llm_calls(output.get("execution_log", []))
    return output, latency_ms, llm_calls


def score_case(case: dict, output: dict) -> dict:
    """Scores whatever ground-truth fields this row actually has -
    different levels have different fields (see
    datasets/routing_ground_truth.jsonl's per-level shapes)."""
    scores: dict = {}

    expected_topics = case.get("expected_topics")
    if expected_topics:
        result = RoutingResult(
            question_id=case["id"],
            expected_topics=expected_topics,
            actual_topics=output.get("selected_topics") or [],
        )
        scores["topic_correct"] = result.is_correct

    if "expected_behavior" in case:
        # Level 5: did the architecture clarify (only C can) vs answer?
        actual_behavior = (
            "clarify" if "clarification_agent" in get_node_sequence(output.get("execution_log", [])) else "answer"
        )
        scores["behavior_correct"] = actual_behavior == case["expected_behavior"]

    if "expected_facts" in case:
        expected_topic = expected_topics[0] if expected_topics else (output.get("selected_topics") or [None])[0]
        final_answer = output.get("final_answer", "")
        retrieved_texts = [p["text"] for p in output.get("retrieved_passages", {}).get(expected_topic, [])]
        result = AnswerResult(
            question_id=case["id"],
            actual_answer=final_answer,
            expected_facts=case["expected_facts"],
            retrieved_texts=retrieved_texts,
            is_answerable=case.get("is_answerable", True),
        )
        scores["answer_correct"] = result.is_correct
    elif "is_answerable" in case and case["is_answerable"] is False:
        # Level 4 unanswerable rows with no expected_facts list at all.
        final_answer = output.get("final_answer", "")
        scores["answer_correct"] = INSUFFICIENT_INFO_MARKER.lower() in final_answer.lower()

    return scores


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", type=str, default=None, help="Path to save raw per-question results as JSON.")
    args = parser.parse_args()

    sample = select_sample()
    print(f"Comparing 3 architectures on a {len(sample)}-question stratified sample "
          f"(Levels {sorted(CORE_LEVELS)} core + {sorted(STRESS_LEVELS)} stress)\n")

    graphs = {name: builder() for name, builder in ARCHITECTURES.items()}

    raw_results: list[dict] = []
    per_arch: dict[str, dict] = {name: defaultdict(list) for name in ARCHITECTURES}

    for i, case in enumerate(sample, start=1):
        print(f"[{i}/{len(sample)}] {case['id']} (L{case['level']}): {case['question'][:80]}")
        for arch_name, graph in graphs.items():
            output, latency_ms, llm_calls = invoke_and_measure(graph, case["question"])
            scores = score_case(case, output)

            raw_results.append(
                {
                    "case_id": case["id"],
                    "level": case["level"],
                    "architecture": arch_name,
                    "latency_ms": round(latency_ms, 1),
                    "llm_calls": llm_calls,
                    "final_answer": output.get("final_answer", ""),
                    **scores,
                }
            )
            per_arch[arch_name]["latency_ms"].append(latency_ms)
            per_arch[arch_name]["llm_calls"].append(llm_calls)
            for key in ("topic_correct", "behavior_correct", "answer_correct"):
                if key in scores:
                    per_arch[arch_name][key].append(scores[key])

    print("\n" + "=" * 78)
    print("RESULTS")
    print("=" * 78)
    header = f"{'Architecture':<26}{'Topic':>10}{'Behavior':>10}{'Answer':>10}{'Avg ms':>10}{'Avg calls':>11}"
    print(header)
    print("-" * len(header))
    summary: dict[str, dict] = {}
    for arch_name in ARCHITECTURES:
        data = per_arch[arch_name]

        def pct(key: str) -> str:
            vals = data.get(key, [])
            return f"{100 * sum(vals) / len(vals):.0f}%" if vals else "n/a"

        avg_latency = sum(data["latency_ms"]) / len(data["latency_ms"])
        avg_calls = sum(data["llm_calls"]) / len(data["llm_calls"])
        print(
            f"{arch_name:<26}{pct('topic_correct'):>10}{pct('behavior_correct'):>10}"
            f"{pct('answer_correct'):>10}{avg_latency:>10.0f}{avg_calls:>11.2f}"
        )
        summary[arch_name] = {
            "topic_accuracy": sum(data["topic_correct"]) / len(data["topic_correct"]) if data.get("topic_correct") else None,
            "behavior_accuracy": sum(data["behavior_correct"]) / len(data["behavior_correct"]) if data.get("behavior_correct") else None,
            "answer_accuracy": sum(data["answer_correct"]) / len(data["answer_correct"]) if data.get("answer_correct") else None,
            "avg_latency_ms": round(avg_latency, 1),
            "avg_llm_calls": round(avg_calls, 2),
            "n": len(data["latency_ms"]),
        }

    if args.save:
        save_path = Path(args.save)
        save_path.write_text(
            json.dumps({"sample_size": len(sample), "summary": summary, "raw_results": raw_results}, indent=2),
            encoding="utf-8",
        )
        print(f"\nSaved full results to {save_path}")

    print("\n" + "=" * 78)
    print("PER-LEVEL BREAKDOWN (topic accuracy / answer accuracy)")
    print("=" * 78)
    by_level_arch: dict[tuple, dict] = defaultdict(lambda: defaultdict(list))
    for r in raw_results:
        key = (r["level"], r["architecture"])
        if "topic_correct" in r:
            by_level_arch[key]["topic"].append(r["topic_correct"])
        if "answer_correct" in r:
            by_level_arch[key]["answer"].append(r["answer_correct"])

    levels = sorted({r["level"] for r in raw_results})
    print(f"{'Level':<6}{'Architecture':<26}{'N':>4}{'Topic':>8}{'Answer':>8}")
    for level in levels:
        for arch_name in ARCHITECTURES:
            d = by_level_arch[(level, arch_name)]
            n = len(d.get("answer") or d.get("topic") or [])
            topic_pct = f"{100 * sum(d['topic']) / len(d['topic']):.0f}%" if d.get("topic") else "n/a"
            answer_pct = f"{100 * sum(d['answer']) / len(d['answer']):.0f}%" if d.get("answer") else "n/a"
            print(f"L{level:<5}{arch_name:<26}{n:>4}{topic_pct:>8}{answer_pct:>8}")


if __name__ == "__main__":
    main()
