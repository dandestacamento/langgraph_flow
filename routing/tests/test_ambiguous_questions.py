"""Level 5 tests: ambiguous questions (clarification and confidence handling).

Loads every Level 5 question from datasets/routing_ground_truth.jsonl, runs
it through the full graph, and checks that the system correctly decided
whether to ask a clarifying question or answer directly - a vague question
with no identifiable subject (e.g. "is it covered?") should clarify; a
self-contained question (e.g. "what does washing machine error E42
indicate?") must NOT be incorrectly flagged as ambiguous.

Both directions are tested together because the "answer" cases are a
regression check: it would be easy to make the ambiguity detector too
aggressive and start asking unnecessary clarifying questions for
perfectly clear questions that happened to be tested fine in Levels 1-4.

Scored deterministically from the execution trace (did clarification_agent
run?), not by inspecting answer text - consistent with Levels 1-4's
"deterministic assertions, not an LLM judge" approach.
"""

from __future__ import annotations

import pytest

from app.evaluation.routing_metrics import ClarificationResult, summarize_clarification
from app.observability.execution_logger import get_node_sequence
from app.state import initial_state
from tests.conftest import load_ground_truth

LEVEL_5_CASES = load_ground_truth(level=5)
assert LEVEL_5_CASES, "No Level 5 cases found in datasets/routing_ground_truth.jsonl"

MIN_CLARIFICATION_ACCURACY = 0.9


def _invoke(compiled_graph, question: str) -> dict:
    return compiled_graph.invoke(initial_state(question))


def _actual_behavior(result: dict) -> str:
    return "clarify" if "clarification_agent" in get_node_sequence(result["execution_log"]) else "answer"


@pytest.mark.parametrize("case", LEVEL_5_CASES, ids=[c["id"] for c in LEVEL_5_CASES])
def test_question_gets_expected_clarification_behavior(compiled_graph, case):
    """Each individual question must clarify or answer exactly as expected -
    no false positives (clear questions wrongly flagged ambiguous) and no
    false negatives (vague questions wrongly answered without clarifying)."""
    result = _invoke(compiled_graph, case["question"])
    actual = _actual_behavior(result)

    assert actual == case["expected_behavior"], (
        f"{case['id']}: expected behavior {case['expected_behavior']!r}, got {actual!r} "
        f"(question: {case['question']!r}, final_answer: {result['final_answer']!r})"
    )


def test_level_5_overall_clarification_accuracy(compiled_graph):
    """Suite-level clarify-vs-answer accuracy across every Level 5 question."""
    results = []
    for case in LEVEL_5_CASES:
        output = _invoke(compiled_graph, case["question"])
        results.append(
            ClarificationResult(
                question_id=case["id"],
                expected_behavior=case["expected_behavior"],
                actual_behavior=_actual_behavior(output),
            )
        )

    summary = summarize_clarification(results)
    print(f"\nLevel 5 clarification summary: {summary}")
    failures = [r.question_id for r in results if not r.is_correct]
    if failures:
        print(f"Failed questions: {failures}")

    assert summary["clarification_accuracy"] >= MIN_CLARIFICATION_ACCURACY, (
        f"Level 5 clarification accuracy {summary['clarification_accuracy']:.0%} is below the "
        f"{MIN_CLARIFICATION_ACCURACY:.0%} target. Failed: {failures}"
    )
