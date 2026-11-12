"""Level 1 tests: simple topic routing.

Loads every Level 1 question from datasets/routing_ground_truth.jsonl, runs
it through the full graph, and checks that the Topic Router selected the
expected topic. Uses deterministic set-equality assertions (per
instructions/Langgraph_routing/4_to_5_obserability.md) rather than an LLM
judge, since "did the router pick the right topic" has one correct answer.

Run with:
    pytest tests/test_basic_routing.py -v
"""

from __future__ import annotations

import pytest

from app.evaluation.routing_metrics import RoutingResult, summarize
from tests.conftest import load_ground_truth

LEVEL_1_CASES = load_ground_truth(level=1)
assert LEVEL_1_CASES, "No Level 1 cases found in datasets/routing_ground_truth.jsonl"

# Target from instructions/Langgraph_routing/7_to_8_routing_configuration.md:
# "at least 95% topic routing accuracy on held-out tests" - treated as a
# target, not a guarantee, so the suite-level assertion below is slightly
# more lenient to avoid flaking on borderline LLM classifications.
MIN_TOPIC_ACCURACY = 0.9


@pytest.mark.parametrize("case", LEVEL_1_CASES, ids=[c["id"] for c in LEVEL_1_CASES])
def test_single_question_routes_to_expected_topic(compiled_graph, case):
    """Each individual question's actual topic set must match its expected
    topic set exactly."""
    result = compiled_graph.invoke(
        {
            "question": case["question"],
            "agent_responses": {},
            "subtopic_decisions": {},
            "selected_subtopics": {},
            "execution_log": [],
        }
    )
    actual_topics = result["selected_topics"]
    assert set(actual_topics) == set(case["expected_topics"]), (
        f"{case['id']}: expected {case['expected_topics']}, got {actual_topics} "
        f"(question: {case['question']!r})"
    )


def test_level_1_overall_topic_accuracy(compiled_graph):
    """Suite-level accuracy check across every Level 1 question, reported
    the way the Streamlit dashboard will later summarize it per level."""
    results = []
    for case in LEVEL_1_CASES:
        output = compiled_graph.invoke(
            {
                "question": case["question"],
                "agent_responses": {},
                "subtopic_decisions": {},
                "selected_subtopics": {},
                "execution_log": [],
            }
        )
        results.append(
            RoutingResult(
                question_id=case["id"],
                expected_topics=case["expected_topics"],
                actual_topics=output["selected_topics"],
            )
        )

    summary = summarize(results)
    print(f"\nLevel 1 routing summary: {summary}")
    failures = [r.question_id for r in results if not r.is_correct]
    if failures:
        print(f"Failed questions: {failures}")

    assert summary["topic_accuracy"] >= MIN_TOPIC_ACCURACY, (
        f"Level 1 topic accuracy {summary['topic_accuracy']:.0%} is below the "
        f"{MIN_TOPIC_ACCURACY:.0%} target. Failed: {failures}"
    )
