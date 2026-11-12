"""Standalone evaluation runner: executes every ground-truth question for
one or more levels through the graph and prints a routing-accuracy
report, without going through pytest. Useful for ad-hoc runs and for the
Streamlit dashboard to shell out to (or import directly).

Only Level 1 (topic routing) has ground-truth coverage and a meaningful
metric so far; later levels will add their own metrics
(subtopic/chapter/retrieval/answer accuracy) as those levels are built.

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

from app.evaluation.routing_metrics import RoutingResult, summarize  # noqa: E402
from app.graph import build_graph  # noqa: E402

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

    results = []
    for case in cases:
        output = graph.invoke({"question": case["question"], "agent_responses": {}, "execution_log": []})
        results.append(
            RoutingResult(
                question_id=case["id"],
                expected_topics=case["expected_topics"],
                actual_topics=output["selected_topics"],
            )
        )
        status = "OK" if results[-1].is_correct else "FAIL"
        print(f"  [{status}] {case['id']}: {case['question']}")
        if not results[-1].is_correct:
            print(f"         expected={case['expected_topics']} actual={output['selected_topics']}")

    summary = summarize(results)
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
