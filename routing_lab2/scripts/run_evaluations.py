"""Standalone evaluation runner: executes every ground-truth question for
one or more levels through the graph and prints an accuracy report,
without going through pytest. Useful for ad-hoc runs and for the
Streamlit dashboard to shell out to (or import directly).

Covers all 10 levels, reusing the exact same metric classes (and
derivation logic from each level's graph output) as the corresponding
pytest file under tests/ - see instructions/learnings/routing-project-learnings.md
section 11, item 2: this used to only support Levels 1-3 correctly and
crash with a KeyError on Level 6+ despite its own "all levels" usage
text, because later levels' ground-truth rows don't have an
`expected_chapter` key at all (Level 6+ uses `expected_chapters`,
`expected_behavior`, `expected_tool`, etc. instead - see each level's
shape in datasets/routing_ground_truth.jsonl).

Usage:
    python scripts/run_evaluations.py --level 1
    python scripts/run_evaluations.py            # all levels with data
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import find_dotenv, load_dotenv  # noqa: E402

load_dotenv(find_dotenv())

from app.cache import enable_llm_cache  # noqa: E402
from app.evaluation.answer_metrics import AnswerResult, summarize_answers  # noqa: E402
from app.evaluation.retrieval_metrics import (  # noqa: E402
    MultiChapterRetrievalResult,
    RetrievalResult,
    summarize_multichapter_retrieval,
    summarize_retrieval,
)
from app.evaluation.routing_metrics import (  # noqa: E402
    ChapterRoutingResult,
    ClarificationResult,
    MultiHopResult,
    RecoveryResult,
    RoutingResult,
    SubtopicRoutingResult,
    ToolSelectionResult,
    summarize,
    summarize_chapter,
    summarize_clarification,
    summarize_multihop,
    summarize_recovery,
    summarize_subtopic,
    summarize_tool_selection,
)
from app.graph import build_graph  # noqa: E402
from app.observability.execution_logger import get_node_sequence  # noqa: E402
from app.state import initial_state  # noqa: E402

enable_llm_cache()

GROUND_TRUTH_PATH = PROJECT_ROOT / "datasets" / "routing_ground_truth.jsonl"


def load_ground_truth(level: int | None = None) -> list[dict]:
    rows = []
    with GROUND_TRUTH_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if level is None or row["level"] == level:
                rows.append(row)
    return rows


def _answer_result(case: dict, answer: str, retrieved_texts: list[str]) -> AnswerResult:
    return AnswerResult(
        question_id=case["id"],
        actual_answer=answer,
        expected_facts=case.get("expected_facts", []),
        retrieved_texts=retrieved_texts,
        is_answerable=case.get("is_answerable", True),
    )


def _topic_answer(output: dict, expected_topic: str) -> tuple[str, list[str]]:
    answer = output.get("agent_responses", {}).get(expected_topic, "")
    retrieved_texts = [p["text"] for p in output.get("retrieved_passages", {}).get(expected_topic, [])]
    return answer, retrieved_texts


def run_level(level: int, graph) -> dict:
    """Invokes every Level `level` ground-truth question through the
    graph and scores it with whatever metric(s) that level's own pytest
    file uses - a different pair of fields/result classes per level, so
    this dispatches on the exact level number rather than assuming later
    levels are a strict superset of earlier ones' ground-truth shape."""
    cases = load_ground_truth(level=level)
    if not cases:
        return {"level": level, "total": 0}

    routing_results: list = []
    answer_results: list[AnswerResult] = []

    for case in cases:
        output = graph.invoke(initial_state(case["question"]))
        expected_topic = case["expected_topics"][0] if case.get("expected_topics") else None
        is_correct = True

        if level == 1:
            result = RoutingResult(
                question_id=case["id"], expected_topics=case["expected_topics"], actual_topics=output["selected_topics"]
            )
            routing_results.append(result)
            is_correct = result.is_correct

        elif level == 2:
            result = SubtopicRoutingResult(
                question_id=case["id"],
                expected_topic=expected_topic,
                expected_subtopic=case["expected_subtopic"],
                actual_topics=output["selected_topics"],
                actual_subtopics=output["selected_subtopics"],
            )
            routing_results.append(result)
            is_correct = result.is_correct

        elif level == 3:
            result = ChapterRoutingResult(
                question_id=case["id"],
                expected_topic=expected_topic,
                expected_subtopic=case["expected_subtopic"],
                expected_chapter=case["expected_chapter"],
                actual_topics=output["selected_topics"],
                actual_subtopics=output["selected_subtopics"],
                actual_chapters=output["selected_chapters"],
            )
            routing_results.append(result)
            is_correct = result.is_correct

        elif level == 4:
            retrieved = output.get("retrieved_passages", {}).get(expected_topic, [])
            result = RetrievalResult(
                question_id=case["id"],
                expected_chapter=case.get("expected_chapter"),
                retrieved_chapter_ids=[p["chapter_id"] for p in retrieved],
            )
            routing_results.append(result)
            is_correct = not case.get("is_answerable", True) or result.is_recalled
            answer, retrieved_texts = _topic_answer(output, expected_topic)
            answer_results.append(_answer_result(case, answer, retrieved_texts))

        elif level == 5:
            actual_behavior = "clarify" if "clarification_agent" in get_node_sequence(output["execution_log"]) else "answer"
            result = ClarificationResult(
                question_id=case["id"], expected_behavior=case["expected_behavior"], actual_behavior=actual_behavior
            )
            routing_results.append(result)
            is_correct = result.is_correct

        elif level == 6:
            retrieved = output.get("retrieved_passages", {}).get(expected_topic, [])
            result = MultiChapterRetrievalResult(
                question_id=case["id"],
                expected_chapters=case["expected_chapters"],
                retrieved_chapter_ids=[p["chapter_id"] for p in retrieved],
            )
            routing_results.append(result)
            is_correct = result.is_fully_covered
            answer, retrieved_texts = _topic_answer(output, expected_topic)
            answer_results.append(_answer_result(case, answer, retrieved_texts))

        elif level == 7:
            result = RoutingResult(
                question_id=case["id"], expected_topics=case["expected_topics"], actual_topics=output["selected_topics"]
            )
            routing_results.append(result)
            is_correct = result.is_correct
            all_retrieved_texts = [p["text"] for passages in output.get("retrieved_passages", {}).values() for p in passages]
            answer_results.append(_answer_result(case, output.get("final_answer", ""), all_retrieved_texts))

        elif level == 8:
            decision = output.get("tool_decisions", {}).get(expected_topic, {})
            result = ToolSelectionResult(
                question_id=case["id"],
                expected_tool=case["expected_tool"],
                actual_needs_tool=decision.get("needs_tool", False),
                actual_tool=decision.get("tool_name"),
            )
            routing_results.append(result)
            is_correct = result.is_correct
            answer, retrieved_texts = _topic_answer(output, expected_topic)
            answer_results.append(_answer_result(case, answer, retrieved_texts))

        elif level == 9:
            hop_results = output.get("hop_results") or []
            hop1_value = hop_results[0]["extracted_value"] if hop_results else None
            result = MultiHopResult(
                question_id=case["id"],
                expected_is_multi_hop=case["expected_is_multi_hop"],
                expected_hop1_fact=case.get("expected_hop1_fact"),
                actual_is_multi_hop=output["is_multi_hop"],
                actual_hop1_value=hop1_value,
            )
            routing_results.append(result)
            is_correct = result.is_correct
            answer_results.append(_answer_result(case, output.get("final_answer", ""), []))

        elif level == 10:
            recovery = output.get("recovery_attempts", {}).get(expected_topic, {})
            result = RecoveryResult(
                question_id=case["id"],
                expected_recovery_attempted=case["expected_needs_recovery"],
                actual_recovery_attempted=recovery.get("attempted", False),
            )
            routing_results.append(result)
            is_correct = result.is_correct
            answer, retrieved_texts = _topic_answer(output, expected_topic)
            answer_results.append(_answer_result(case, answer, retrieved_texts))

        else:
            continue

        status = "OK" if is_correct else "FAIL"
        print(f"  [{status}] {case['id']}: {case['question']}")

    summary: dict = {}
    if level == 1:
        summary = summarize(routing_results)
    elif level == 2:
        summary = summarize_subtopic(routing_results)
    elif level == 3:
        summary = summarize_chapter(routing_results)
    elif level == 4:
        summary = {**summarize_retrieval(routing_results), **summarize_answers(answer_results)}
    elif level == 5:
        summary = summarize_clarification(routing_results)
    elif level == 6:
        summary = {**summarize_multichapter_retrieval(routing_results), **summarize_answers(answer_results)}
    elif level == 7:
        summary = {**summarize(routing_results), **summarize_answers(answer_results)}
    elif level == 8:
        summary = {**summarize_tool_selection(routing_results), **summarize_answers(answer_results)}
    elif level == 9:
        summary = {**summarize_multihop(routing_results), **summarize_answers(answer_results)}
    elif level == 10:
        summary = {**summarize_recovery(routing_results), **summarize_answers(answer_results)}

    summary["level"] = level
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--level", type=int, default=None, help="Run only this level (default: all).")
    args = parser.parse_args()

    graph = build_graph()
    levels = [args.level] if args.level is not None else sorted({row["level"] for row in load_ground_truth()})

    print("Routing Accuracy Lab - evaluation run")
    print("=" * 50)
    for level in levels:
        print(f"\nLevel {level}:")
        summary = run_level(level, graph)
        print(f"  Summary: {summary}")


if __name__ == "__main__":
    main()
