"""Level 9 tests: complex multi-hop reasoning.

Loads every Level 9 question from datasets/routing_ground_truth.jsonl and
runs it through the full graph, checking three independent things:

1. Multi-hop detection: did the Multi-Hop Router correctly decide this
   question is (or, for the two regression-check questions, is NOT)
   genuinely multi-hop - a second part whose subject isn't named until a
   first part identifies it? Misclassifying an ordinary question as
   multi-hop would trigger two extra full pipeline invocations for no
   reason, so this is scored both ways, not just "did it detect genuine
   cases", consistent with Level 8's tool-selection accuracy.
2. Hop 1 resolution: for a genuinely multi-hop question, did hop 1
   resolve to the expected entity (e.g. "WM-900")? This is the specific
   new failure mode Level 9 introduces that no earlier level has - hop 2
   is only as good as the value substituted into its `{hop1_answer}`
   placeholder.
3. Answer: does the final, synthesized answer contain the expected facts
   from BOTH hops - proving hop 2 was actually resolved using hop 1's
   real answer, not a hallucinated or generic one.

All scored deterministically (boolean/substring matching), not an LLM
judge - consistent with Levels 1-8.
"""

from __future__ import annotations

import pytest

from app.evaluation.answer_metrics import AnswerResult, summarize_answers
from app.evaluation.routing_metrics import MultiHopResult, summarize_multihop
from app.state import initial_state
from tests.conftest import load_ground_truth

LEVEL_9_CASES = load_ground_truth(level=9)
assert LEVEL_9_CASES, "No Level 9 cases found in datasets/routing_ground_truth.jsonl"

MULTIHOP_CASES = [c for c in LEVEL_9_CASES if c["expected_is_multi_hop"]]
REGRESSION_CASES = [c for c in LEVEL_9_CASES if not c["expected_is_multi_hop"]]

MIN_MULTIHOP_ACCURACY = 0.9
MIN_ANSWER_ACCURACY = 0.85


def _invoke(compiled_graph, question: str) -> dict:
    return compiled_graph.invoke(initial_state(question))


def _hop1_value(output: dict) -> str | None:
    hop_results = output.get("hop_results") or []
    return hop_results[0]["extracted_value"] if hop_results else None


@pytest.mark.parametrize("case", LEVEL_9_CASES, ids=[c["id"] for c in LEVEL_9_CASES])
def test_multihop_detection_matches_expected(compiled_graph, case):
    """The Multi-Hop Router must correctly decide is_multi_hop - and,
    when true, hop 1 must resolve to the expected entity."""
    output = _invoke(compiled_graph, case["question"])

    result = MultiHopResult(
        question_id=case["id"],
        expected_is_multi_hop=case["expected_is_multi_hop"],
        expected_hop1_fact=case["expected_hop1_fact"],
        actual_is_multi_hop=output["is_multi_hop"],
        actual_hop1_value=_hop1_value(output),
    )
    assert result.is_correct, (
        f"{case['id']}: expected is_multi_hop={case['expected_is_multi_hop']!r} "
        f"(hop1_fact={case['expected_hop1_fact']!r}), got is_multi_hop={output['is_multi_hop']!r} "
        f"(hop1_value={_hop1_value(output)!r}) (question: {case['question']!r})"
    )


@pytest.mark.parametrize("case", LEVEL_9_CASES, ids=[c["id"] for c in LEVEL_9_CASES])
def test_final_answer_contains_facts_from_both_hops(compiled_graph, case):
    """The final (synthesized, for genuine multi-hop cases) answer must
    contain every expected fact, proving hop 2 was resolved using hop 1's
    real answer rather than a hallucinated one."""
    output = _invoke(compiled_graph, case["question"])

    result = AnswerResult(
        question_id=case["id"],
        actual_answer=output["final_answer"],
        expected_facts=case["expected_facts"],
        retrieved_texts=[],
        is_answerable=True,
    )
    assert result.is_correct, (
        f"{case['id']}: final answer missing expected facts {case['expected_facts']} "
        f"(correctness={result.correctness:.2f}). Final answer was: {output['final_answer']!r}"
    )


def test_level_9_overall_multihop_accuracy(compiled_graph):
    """Suite-level multi-hop detection accuracy across every Level 9 question."""
    results = []
    for case in LEVEL_9_CASES:
        output = _invoke(compiled_graph, case["question"])
        results.append(
            MultiHopResult(
                question_id=case["id"],
                expected_is_multi_hop=case["expected_is_multi_hop"],
                expected_hop1_fact=case["expected_hop1_fact"],
                actual_is_multi_hop=output["is_multi_hop"],
                actual_hop1_value=_hop1_value(output),
            )
        )

    summary = summarize_multihop(results)
    print(f"\nLevel 9 multi-hop detection summary: {summary}")
    failures = [r.question_id for r in results if not r.is_correct]
    if failures:
        print(f"Failed questions: {failures}")

    assert summary["multihop_accuracy"] >= MIN_MULTIHOP_ACCURACY, (
        f"Level 9 multi-hop accuracy {summary['multihop_accuracy']:.0%} is below the "
        f"{MIN_MULTIHOP_ACCURACY:.0%} target. Failed: {failures}"
    )


def test_level_9_overall_answer_accuracy(compiled_graph):
    """Suite-level answer accuracy across every Level 9 question."""
    results = []
    for case in LEVEL_9_CASES:
        output = _invoke(compiled_graph, case["question"])
        results.append(
            AnswerResult(
                question_id=case["id"],
                actual_answer=output["final_answer"],
                expected_facts=case["expected_facts"],
                retrieved_texts=[],
                is_answerable=True,
            )
        )

    summary = summarize_answers(results)
    print(f"\nLevel 9 answer summary: {summary}")
    failures = [r.question_id for r in results if not r.is_correct]
    if failures:
        print(f"Failed questions: {failures}")

    assert summary["answer_accuracy"] >= MIN_ANSWER_ACCURACY, (
        f"Level 9 answer accuracy {summary['answer_accuracy']:.0%} is below the "
        f"{MIN_ANSWER_ACCURACY:.0%} target. Failed: {failures}"
    )
