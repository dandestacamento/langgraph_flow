"""Level 2 tests: subtopic routing.

Loads every Level 2 question from datasets/routing_ground_truth.jsonl, runs
it through the full graph, and checks that the Subtopic Router selected
the expected subtopic within the expected topic. Uses deterministic
equality assertions, consistent with Level 1 (see
instructions/Langgraph_routing/4_to_5_obserability.md).
"""

from __future__ import annotations

import pytest

from app.evaluation.routing_metrics import SubtopicRoutingResult, summarize_subtopic
from app.state import initial_state
from tests.conftest import load_ground_truth

LEVEL_2_CASES = load_ground_truth(level=2)
assert LEVEL_2_CASES, "No Level 2 cases found in datasets/routing_ground_truth.jsonl"

MIN_SUBTOPIC_ACCURACY = 0.9


def _invoke(compiled_graph, question: str) -> dict:
    return compiled_graph.invoke(initial_state(question))


@pytest.mark.parametrize("case", LEVEL_2_CASES, ids=[c["id"] for c in LEVEL_2_CASES])
def test_single_question_routes_to_expected_subtopic(compiled_graph, case):
    """Each individual question must select both the expected topic and,
    within it, the expected subtopic."""
    result = _invoke(compiled_graph, case["question"])
    expected_topic = case["expected_topics"][0]
    actual_topics = result["selected_topics"]
    actual_subtopic = result["selected_subtopics"].get(expected_topic)

    assert expected_topic in actual_topics, (
        f"{case['id']}: expected topic {expected_topic!r} not selected (got {actual_topics}) "
        f"(question: {case['question']!r})"
    )
    assert actual_subtopic == case["expected_subtopic"], (
        f"{case['id']}: expected subtopic {case['expected_subtopic']!r}, got {actual_subtopic!r} "
        f"(question: {case['question']!r})"
    )


def test_level_2_overall_subtopic_accuracy(compiled_graph):
    """Suite-level subtopic accuracy check across every Level 2 question."""
    results = []
    for case in LEVEL_2_CASES:
        output = _invoke(compiled_graph, case["question"])
        expected_topic = case["expected_topics"][0]
        results.append(
            SubtopicRoutingResult(
                question_id=case["id"],
                expected_topic=expected_topic,
                expected_subtopic=case["expected_subtopic"],
                actual_topics=output["selected_topics"],
                actual_subtopics=output["selected_subtopics"],
            )
        )

    summary = summarize_subtopic(results)
    print(f"\nLevel 2 routing summary: {summary}")
    failures = [r.question_id for r in results if not r.is_correct]
    if failures:
        print(f"Failed questions: {failures}")

    assert summary["subtopic_accuracy"] >= MIN_SUBTOPIC_ACCURACY, (
        f"Level 2 subtopic accuracy {summary['subtopic_accuracy']:.0%} is below the "
        f"{MIN_SUBTOPIC_ACCURACY:.0%} target. Failed: {failures}"
    )
