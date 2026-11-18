"""Level 3 tests: chapter routing.

Loads every Level 3 question from datasets/routing_ground_truth.jsonl, runs
it through the full graph, and checks that the Chapter Selector picked the
expected chapter_id within the expected topic and subtopic. Uses
deterministic equality assertions, consistent with Levels 1-2 (see
instructions/Langgraph_routing/4_to_5_obserability.md).
"""

from __future__ import annotations

import pytest

from app.evaluation.routing_metrics import ChapterRoutingResult, summarize_chapter
from app.state import initial_state
from tests.conftest import load_ground_truth

LEVEL_3_CASES = load_ground_truth(level=3)
assert LEVEL_3_CASES, "No Level 3 cases found in datasets/routing_ground_truth.jsonl"

MIN_CHAPTER_ACCURACY = 0.9


def _invoke(compiled_graph, question: str) -> dict:
    return compiled_graph.invoke(initial_state(question))


@pytest.mark.parametrize("case", LEVEL_3_CASES, ids=[c["id"] for c in LEVEL_3_CASES])
def test_single_question_routes_to_expected_chapter(compiled_graph, case):
    """Each individual question must select the expected topic, subtopic,
    and chapter_id all together."""
    result = _invoke(compiled_graph, case["question"])
    expected_topic = case["expected_topics"][0]
    actual_topics = result["selected_topics"]
    actual_subtopic = result["selected_subtopics"].get(expected_topic)
    actual_chapter = result["selected_chapters"].get(expected_topic)

    assert expected_topic in actual_topics, (
        f"{case['id']}: expected topic {expected_topic!r} not selected (got {actual_topics}) "
        f"(question: {case['question']!r})"
    )
    assert actual_subtopic == case["expected_subtopic"], (
        f"{case['id']}: expected subtopic {case['expected_subtopic']!r}, got {actual_subtopic!r} "
        f"(question: {case['question']!r})"
    )
    assert actual_chapter == case["expected_chapter"], (
        f"{case['id']}: expected chapter {case['expected_chapter']!r}, got {actual_chapter!r} "
        f"(question: {case['question']!r})"
    )


def test_level_3_overall_chapter_accuracy(compiled_graph):
    """Suite-level chapter accuracy check across every Level 3 question."""
    results = []
    for case in LEVEL_3_CASES:
        output = _invoke(compiled_graph, case["question"])
        expected_topic = case["expected_topics"][0]
        results.append(
            ChapterRoutingResult(
                question_id=case["id"],
                expected_topic=expected_topic,
                expected_subtopic=case["expected_subtopic"],
                expected_chapter=case["expected_chapter"],
                actual_topics=output["selected_topics"],
                actual_subtopics=output["selected_subtopics"],
                actual_chapters=output["selected_chapters"],
            )
        )

    summary = summarize_chapter(results)
    print(f"\nLevel 3 routing summary: {summary}")
    failures = [r.question_id for r in results if not r.is_correct]
    if failures:
        print(f"Failed questions: {failures}")

    assert summary["chapter_accuracy"] >= MIN_CHAPTER_ACCURACY, (
        f"Level 3 chapter accuracy {summary['chapter_accuracy']:.0%} is below the "
        f"{MIN_CHAPTER_ACCURACY:.0%} target. Failed: {failures}"
    )
