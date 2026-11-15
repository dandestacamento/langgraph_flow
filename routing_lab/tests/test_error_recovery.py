"""Level 10 tests: error recovery and fallback.

Two kinds of tests, for two different reasons:

1. **Dataset-driven, end-to-end tests** (`LEVEL_10_CASES`, via the full
   compiled graph): verify the *decision* to attempt recovery is correct
   - attempted for genuinely unanswerable questions (even though it's
   expected to still fail afterward - recovery being *attempted* is what
   Level 10 tests, not that an impossible question somehow succeeds), and
   NOT attempted for ordinary questions that should succeed on the first
   try (an unnecessary retry is itself a mistake - wasted cost for no
   reason, consistent with Level 8's tool-selection "efficiency"
   reasoning). Also verifies no hallucination: a genuinely unanswerable
   question must still correctly report insufficient information after
   recovery is exhausted, not fabricate an answer.

2. **Direct mechanism tests** (hardcoded, bypassing the full graph):
   Levels 1-9 all reused real end-to-end questions for every test case,
   but Level 10's two recovery paths are hard to reliably *provoke* live
   - a wrong subtopic guess or a tool error are things the pipeline
   mostly no longer makes (after nine levels of fixing exactly those
   kinds of mistakes). Rather than writing brittle tests that depend on
   the live pipeline *happening* to fail a specific way, these construct
   the failure directly (a deliberately wrong `selected_subtopics` entry,
   a deliberately malformed SQL query) and call `run_topic_agent`/
   `_retry_tool` directly - the same "test the deterministic mechanism
   directly" approach already used for the calculator's safety and the
   SQL tool's column-type handling in Level 8.
"""

from __future__ import annotations

import pytest

from app.agents._shared import _retry_tool, run_topic_agent
from app.evaluation.answer_metrics import AnswerResult, summarize_answers
from app.evaluation.routing_metrics import RecoveryResult, summarize_recovery
from app.state import initial_state
from tests.conftest import load_ground_truth

LEVEL_10_CASES = load_ground_truth(level=10)
assert LEVEL_10_CASES, "No Level 10 cases found in datasets/routing_ground_truth.jsonl"

MIN_RECOVERY_DECISION_ACCURACY = 0.9
MIN_ANSWER_ACCURACY = 0.85


def _invoke(compiled_graph, question: str) -> dict:
    return compiled_graph.invoke(initial_state(question))


@pytest.mark.parametrize("case", LEVEL_10_CASES, ids=[c["id"] for c in LEVEL_10_CASES])
def test_recovery_attempted_matches_expected(compiled_graph, case):
    """Recovery must be attempted exactly when expected - for a
    genuinely unanswerable question (even though it will still fail), and
    NOT for an ordinary question that succeeds on the first attempt."""
    output = _invoke(compiled_graph, case["question"])
    expected_topic = case["expected_topics"][0]
    recovery = output["recovery_attempts"].get(expected_topic, {})

    result = RecoveryResult(
        question_id=case["id"],
        expected_recovery_attempted=case["expected_needs_recovery"],
        actual_recovery_attempted=recovery.get("attempted", False),
    )
    assert result.is_correct, (
        f"{case['id']}: expected recovery attempted={case['expected_needs_recovery']!r}, got "
        f"{recovery.get('attempted')!r} (reason={recovery.get('reason')!r}, "
        f"question: {case['question']!r})"
    )


@pytest.mark.parametrize("case", LEVEL_10_CASES, ids=[c["id"] for c in LEVEL_10_CASES])
def test_answer_correct_or_gracefully_declines(compiled_graph, case):
    """An answerable question must still answer correctly (possibly
    after a recovery retry); a genuinely unanswerable one must still
    correctly report insufficient information, not fabricate, even after
    recovery was attempted and failed."""
    output = _invoke(compiled_graph, case["question"])
    expected_topic = case["expected_topics"][0]
    answer = output["agent_responses"].get(expected_topic, "")
    retrieved_texts = [p["text"] for p in output["retrieved_passages"].get(expected_topic, [])]

    result = AnswerResult(
        question_id=case["id"],
        actual_answer=answer,
        expected_facts=case["expected_facts"],
        retrieved_texts=retrieved_texts,
        is_answerable=case["is_answerable"],
    )
    assert result.is_correct, (
        f"{case['id']}: expected is_answerable={case['is_answerable']!r} with facts "
        f"{case['expected_facts']}, got answer: {answer!r}"
    )


def test_level_10_overall_recovery_decision_accuracy(compiled_graph):
    """Suite-level recovery-decision accuracy across every Level 10 question."""
    results = []
    for case in LEVEL_10_CASES:
        output = _invoke(compiled_graph, case["question"])
        expected_topic = case["expected_topics"][0]
        recovery = output["recovery_attempts"].get(expected_topic, {})
        results.append(
            RecoveryResult(
                question_id=case["id"],
                expected_recovery_attempted=case["expected_needs_recovery"],
                actual_recovery_attempted=recovery.get("attempted", False),
            )
        )

    summary = summarize_recovery(results)
    print(f"\nLevel 10 recovery decision summary: {summary}")
    failures = [r.question_id for r in results if not r.is_correct]
    if failures:
        print(f"Failed questions: {failures}")

    assert summary["recovery_decision_accuracy"] >= MIN_RECOVERY_DECISION_ACCURACY, (
        f"Level 10 recovery decision accuracy {summary['recovery_decision_accuracy']:.0%} is below "
        f"the {MIN_RECOVERY_DECISION_ACCURACY:.0%} target. Failed: {failures}"
    )


def test_level_10_overall_answer_accuracy(compiled_graph):
    """Suite-level answer accuracy (correct answers + correct graceful
    declines) across every Level 10 question."""
    results = []
    for case in LEVEL_10_CASES:
        output = _invoke(compiled_graph, case["question"])
        expected_topic = case["expected_topics"][0]
        answer = output["agent_responses"].get(expected_topic, "")
        retrieved_texts = [p["text"] for p in output["retrieved_passages"].get(expected_topic, [])]
        results.append(
            AnswerResult(
                question_id=case["id"],
                actual_answer=answer,
                expected_facts=case["expected_facts"],
                retrieved_texts=retrieved_texts,
                is_answerable=case["is_answerable"],
            )
        )

    summary = summarize_answers(results)
    print(f"\nLevel 10 answer summary: {summary}")
    failures = [r.question_id for r in results if not r.is_correct]
    if failures:
        print(f"Failed questions: {failures}")

    assert summary["answer_accuracy"] >= MIN_ANSWER_ACCURACY, (
        f"Level 10 answer accuracy {summary['answer_accuracy']:.0%} is below the "
        f"{MIN_ANSWER_ACCURACY:.0%} target. Failed: {failures}"
    )


# --- Direct mechanism tests (bypass the full graph; see module docstring) ---


def test_recovery_recovers_from_wrong_subtopic_guess():
    """If `selected_subtopics` is wrong and nothing relevant was
    retrieved under it, broadening retrieval to the whole topic must
    still find the right chapter and answer correctly."""
    state = {
        "question": "What does washing machine error E42 indicate?",
        "selected_topics": ["appliances"],
        "selected_subtopics": {"appliances": "refrigerators"},  # deliberately wrong
        "retrieved_passages": {"appliances": []},
        "tool_decisions": {},
        "tool_results": {},
    }
    result = run_topic_agent("appliances", state)
    recovery = result["recovery_attempts"]["appliances"]
    answer = result["agent_responses"]["appliances"]

    assert recovery["attempted"] is True
    assert recovery["succeeded"] is True
    assert "door lock" in answer.lower()


def test_recovery_recovers_from_wrong_subtopic_guess_customer_support():
    """Same recovery pattern, verified for a second topic/question to
    confirm it isn't specific to one chapter's retrieval quirk."""
    state = {
        "question": "What's included in White Glove delivery?",
        "selected_topics": ["customer_support"],
        "selected_subtopics": {"customer_support": "refunds"},  # deliberately wrong
        "retrieved_passages": {"customer_support": []},
        "tool_decisions": {},
        "tool_results": {},
    }
    result = run_topic_agent("customer_support", state)
    recovery = result["recovery_attempts"]["customer_support"]
    answer = result["agent_responses"]["customer_support"]

    assert recovery["attempted"] is True
    assert recovery["succeeded"] is True
    assert "installation" in answer.lower()


def test_retry_tool_self_corrects_wrong_column_name():
    """A sql_query with a hallucinated/typo'd column name must be
    self-corrected to the real column and re-executed successfully."""
    output, error = _retry_tool(
        "appliances",
        "washing_machines",
        "sql_query",
        "SELECT pricing FROM specifications WHERE model = 'WM-900'",
        "no such column: pricing",
    )
    assert error is None
    assert "1499" in output


def test_retry_tool_self_corrects_sql_syntax_error():
    """A sql_query with a SQL syntax error (missing quotes around a
    string literal) must be self-corrected and re-executed successfully."""
    output, error = _retry_tool(
        "appliances",
        "washing_machines",
        "sql_query",
        "SELECT price_aud FROM specifications WHERE model = WM-900",
        'near "-": syntax error',
    )
    assert error is None
    assert "1499" in output
