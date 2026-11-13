"""Level 8 tests: tool selection and execution.

Loads every Level 8 question from datasets/routing_ground_truth.jsonl and
runs it through the full graph, checking three independent things:

1. Tool selection: did the Tool Router pick the expected tool - or
   correctly decide no tool was needed, for the two regression-check
   questions reused from earlier levels? An unnecessary tool call is
   itself a routing mistake (see the "Efficiency" evaluation question in
   instructions/Langgraph_routing/1_architecture.md), so this is scored
   both ways, not just "did it pick the right tool when one WAS needed".
2. Tool execution: did the selected tool actually run without error?
   (A correct tool *selection* with a malformed query/expression would
   otherwise pass the selection check but silently fail to help the
   final answer - this is checked separately via `execution_log`.)
3. Answer: does the agent's final answer contain the expected fact -
   proving the tool's result (not just its selection) made it into a
   correct, grounded answer.

All scored deterministically (tool-name equality, execution_log
inspection, substring fact matching), not an LLM judge - consistent with
Levels 1-7.
"""

from __future__ import annotations

import pytest

from app.evaluation.answer_metrics import AnswerResult, summarize_answers
from app.evaluation.routing_metrics import ToolSelectionResult, summarize_tool_selection
from app.state import initial_state
from tests.conftest import load_ground_truth

LEVEL_8_CASES = load_ground_truth(level=8)
assert LEVEL_8_CASES, "No Level 8 cases found in datasets/routing_ground_truth.jsonl"

TOOL_CASES = [c for c in LEVEL_8_CASES if c["expected_tool"] is not None]
NO_TOOL_CASES = [c for c in LEVEL_8_CASES if c["expected_tool"] is None]

MIN_TOOL_SELECTION_ACCURACY = 0.9
MIN_ANSWER_ACCURACY = 0.85


def _invoke(compiled_graph, question: str) -> dict:
    return compiled_graph.invoke(initial_state(question))


@pytest.mark.parametrize("case", LEVEL_8_CASES, ids=[c["id"] for c in LEVEL_8_CASES])
def test_tool_decision_matches_expected(compiled_graph, case):
    """The Tool Router must select the expected tool - or, for the
    regression-check questions, correctly decide no tool was needed."""
    output = _invoke(compiled_graph, case["question"])
    expected_topic = case["expected_topics"][0]
    decision = output["tool_decisions"].get(expected_topic, {})

    result = ToolSelectionResult(
        question_id=case["id"],
        expected_tool=case["expected_tool"],
        actual_needs_tool=decision.get("needs_tool", False),
        actual_tool=decision.get("tool_name"),
    )
    assert result.is_correct, (
        f"{case['id']}: expected tool {case['expected_tool']!r}, got needs_tool="
        f"{decision.get('needs_tool')!r} tool_name={decision.get('tool_name')!r} "
        f"(question: {case['question']!r}, reasoning: {decision.get('reasoning')!r})"
    )


@pytest.mark.parametrize("case", TOOL_CASES, ids=[c["id"] for c in TOOL_CASES])
def test_tool_executes_without_error(compiled_graph, case):
    """For a question that genuinely needs a tool, it must actually run
    successfully - not just be selected."""
    output = _invoke(compiled_graph, case["question"])
    expected_topic = case["expected_topics"][0]
    tool_result = output["tool_results"].get(expected_topic)

    assert tool_result is not None, f"{case['id']}: expected tool {case['expected_tool']!r} to run, but it didn't"
    assert tool_result["error"] is None, (
        f"{case['id']}: tool {tool_result['tool_name']!r} failed on input "
        f"{tool_result['tool_input']!r}: {tool_result['error']}"
    )


@pytest.mark.parametrize("case", LEVEL_8_CASES, ids=[c["id"] for c in LEVEL_8_CASES])
def test_answer_contains_expected_fact(compiled_graph, case):
    """The final answer must contain the expected fact, proving the
    tool's result (or, for the regression checks, the retrieved
    passages) made it into a correct answer."""
    output = _invoke(compiled_graph, case["question"])
    expected_topic = case["expected_topics"][0]
    answer = output["agent_responses"].get(expected_topic, "")
    retrieved_texts = [p["text"] for p in output["retrieved_passages"].get(expected_topic, [])]

    result = AnswerResult(
        question_id=case["id"],
        actual_answer=answer,
        expected_facts=case["expected_facts"],
        retrieved_texts=retrieved_texts,
        is_answerable=True,
    )
    assert result.is_correct, (
        f"{case['id']}: answer missing expected facts {case['expected_facts']} "
        f"(correctness={result.correctness:.2f}). Answer was: {answer!r}"
    )


def test_level_8_overall_tool_selection_accuracy(compiled_graph):
    """Suite-level tool-selection accuracy across every Level 8 question."""
    results = []
    for case in LEVEL_8_CASES:
        output = _invoke(compiled_graph, case["question"])
        expected_topic = case["expected_topics"][0]
        decision = output["tool_decisions"].get(expected_topic, {})
        results.append(
            ToolSelectionResult(
                question_id=case["id"],
                expected_tool=case["expected_tool"],
                actual_needs_tool=decision.get("needs_tool", False),
                actual_tool=decision.get("tool_name"),
            )
        )

    summary = summarize_tool_selection(results)
    print(f"\nLevel 8 tool selection summary: {summary}")
    failures = [r.question_id for r in results if not r.is_correct]
    if failures:
        print(f"Failed questions: {failures}")

    assert summary["tool_selection_accuracy"] >= MIN_TOOL_SELECTION_ACCURACY, (
        f"Level 8 tool selection accuracy {summary['tool_selection_accuracy']:.0%} is below the "
        f"{MIN_TOOL_SELECTION_ACCURACY:.0%} target. Failed: {failures}"
    )


def test_level_8_overall_answer_accuracy(compiled_graph):
    """Suite-level answer accuracy across every Level 8 question."""
    results = []
    for case in LEVEL_8_CASES:
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
                is_answerable=True,
            )
        )

    summary = summarize_answers(results)
    print(f"\nLevel 8 answer summary: {summary}")
    failures = [r.question_id for r in results if not r.is_correct]
    if failures:
        print(f"Failed questions: {failures}")

    assert summary["answer_accuracy"] >= MIN_ANSWER_ACCURACY, (
        f"Level 8 answer accuracy {summary['answer_accuracy']:.0%} is below the "
        f"{MIN_ANSWER_ACCURACY:.0%} target. Failed: {failures}"
    )
