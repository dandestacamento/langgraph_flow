"""Standalone evaluation runner: executes every ground-truth question for
one or more levels through the graph and prints a routing-accuracy
report, without going through pytest. Useful for ad-hoc runs and for the
Streamlit dashboard to shell out to (or import directly).

Level 1 is scored on topic accuracy; Level 2 is scored on subtopic
accuracy (within the expected topic); Level 3 is scored on chapter
accuracy (within the expected topic and subtopic).

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

from app.evaluation.routing_metrics import (  # noqa: E402
    ChapterRoutingResult,
    RoutingResult,
    SubtopicRoutingResult,
    summarize,
    summarize_chapter,
    summarize_subtopic,
)
from app.graph import build_graph  # noqa: E402
from app.state import initial_state  # noqa: E402

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


def run_level(level: int, graph) -> dict:
    cases = load_ground_truth(level=level)
    if not cases:
        return {"level": level, "total": 0}

    topic_results = []
    subtopic_results = []
    chapter_results = []
    for case in cases:
        output = graph.invoke(initial_state(case["question"]))
        topic_result = RoutingResult(
            question_id=case["id"],
            expected_topics=case["expected_topics"],
            actual_topics=output["selected_topics"],
        )
        topic_results.append(topic_result)
        is_correct = topic_result.is_correct

        if level >= 2:
            expected_topic = case["expected_topics"][0]
            subtopic_result = SubtopicRoutingResult(
                question_id=case["id"],
                expected_topic=expected_topic,
                expected_subtopic=case["expected_subtopic"],
                actual_topics=output["selected_topics"],
                actual_subtopics=output["selected_subtopics"],
            )
            subtopic_results.append(subtopic_result)
            is_correct = subtopic_result.is_correct

        if level >= 3:
            chapter_result = ChapterRoutingResult(
                question_id=case["id"],
                expected_topic=expected_topic,
                expected_subtopic=case["expected_subtopic"],
                expected_chapter=case["expected_chapter"],
                actual_topics=output["selected_topics"],
                actual_subtopics=output["selected_subtopics"],
                actual_chapters=output["selected_chapters"],
            )
            chapter_results.append(chapter_result)
            is_correct = chapter_result.is_correct

        status = "OK" if is_correct else "FAIL"
        print(f"  [{status}] {case['id']}: {case['question']}")
        if not is_correct:
            print(
                f"         expected_topic={case['expected_topics']} actual_topics={output['selected_topics']} "
                f"expected_subtopic={case.get('expected_subtopic')} "
                f"actual_subtopics={output['selected_subtopics']} "
                f"expected_chapter={case.get('expected_chapter')} "
                f"actual_chapters={output['selected_chapters']}"
            )

    if level >= 3:
        summary = summarize_chapter(chapter_results)
    elif level == 2:
        summary = summarize_subtopic(subtopic_results)
    else:
        summary = summarize(topic_results)
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
