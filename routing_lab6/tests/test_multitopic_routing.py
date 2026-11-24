"""Level 7 tests: multiple topics (parallel agent routing).

Loads every Level 7 question from datasets/routing_ground_truth.jsonl and
runs it through the full graph, checking three independent things:

1. Routing: did the Topic Router select exactly the expected set of
   topics - neither missing a needed topic nor adding an unnecessary one?
   (Scored with the same `RoutingResult`/exact-set-match used since
   Level 1, now exercised with genuinely multi-topic expected sets for
   the first time.)
2. Parallel execution: for multi-topic questions, did every expected
   topic's agent actually run (via the `Send` fan-out from
   `app.graph.route_to_agents`), each producing its own grounded answer?
3. Synthesis: does the final, synthesized answer still contain the
   expected facts from every topic involved - proving the Synthesis
   Agent's LLM merge step didn't drop or corrupt any topic's contribution?

Two of the ten questions are single-topic regression checks (reused
verbatim from Level 5's dataset) - these exist because Level 7 is the
first time the Topic Router is asked to actively consider whether a
question needs *more than one* topic, which creates a new failure mode
not present in Levels 1-6: over-eagerly flagging a single-topic question
as multi-topic.

All scored deterministically (topic-set membership, substring fact
matching), not an LLM judge - consistent with Levels 1-6.
"""

from __future__ import annotations

import pytest

from app.evaluation.answer_metrics import AnswerResult, summarize_answers
from app.evaluation.routing_metrics import RoutingResult, summarize
from app.state import initial_state
from tests.conftest import load_ground_truth

LEVEL_7_CASES = load_ground_truth(level=7)
assert LEVEL_7_CASES, "No Level 7 cases found in datasets/routing_ground_truth.jsonl"

MULTI_TOPIC_CASES = [c for c in LEVEL_7_CASES if len(c["expected_topics"]) > 1]
SINGLE_TOPIC_CASES = [c for c in LEVEL_7_CASES if len(c["expected_topics"]) == 1]

MIN_TOPIC_ACCURACY = 0.9
MIN_ANSWER_ACCURACY = 0.85


def _invoke(compiled_graph, question: str) -> dict:
    return compiled_graph.invoke(initial_state(question))


@pytest.mark.parametrize("case", LEVEL_7_CASES, ids=[c["id"] for c in LEVEL_7_CASES])
def test_topic_set_matches_expected(compiled_graph, case):
    """The Topic Router must select exactly the expected topic set - this
    is the first level where that set can genuinely have more than one
    member, so it also guards against over-eager multi-topic flagging on
    the single-topic regression cases."""
    output = _invoke(compiled_graph, case["question"])
    actual_topics = output["selected_topics"]

    assert set(actual_topics) == set(case["expected_topics"]), (
        f"{case['id']}: expected topics {case['expected_topics']}, got {actual_topics} "
        f"(question: {case['question']!r})"
    )


@pytest.mark.parametrize("case", MULTI_TOPIC_CASES, ids=[c["id"] for c in MULTI_TOPIC_CASES])
def test_every_expected_topic_agent_runs(compiled_graph, case):
    """For a multi-topic question, every expected topic's agent must
    actually produce a response - proving the `Send` fan-out ran all of
    them in parallel, not just the first one selected."""
    output = _invoke(compiled_graph, case["question"])
    responded_topics = set(output["agent_responses"].keys())

    missing = set(case["expected_topics"]) - responded_topics
    assert not missing, (
        f"{case['id']}: topic agent(s) {missing} never ran (responded: {responded_topics}, "
        f"question: {case['question']!r})"
    )


@pytest.mark.parametrize("case", LEVEL_7_CASES, ids=[c["id"] for c in LEVEL_7_CASES])
def test_final_answer_contains_facts_from_every_topic(compiled_graph, case):
    """The final (synthesized, for multi-topic cases) answer must contain
    every expected fact - proving synthesis preserves every topic's
    contribution rather than dropping one in favor of another."""
    output = _invoke(compiled_graph, case["question"])
    all_retrieved_texts = [
        p["text"] for passages in output["retrieved_passages"].values() for p in passages
    ]

    result = AnswerResult(
        question_id=case["id"],
        actual_answer=output["final_answer"],
        expected_facts=case["expected_facts"],
        retrieved_texts=all_retrieved_texts,
        is_answerable=True,
    )
    assert result.is_correct, (
        f"{case['id']}: final answer missing expected facts {case['expected_facts']} "
        f"(correctness={result.correctness:.2f}). Final answer was: {output['final_answer']!r}"
    )


def test_level_7_overall_topic_accuracy(compiled_graph):
    """Suite-level topic-set accuracy across every Level 7 question."""
    results = []
    for case in LEVEL_7_CASES:
        output = _invoke(compiled_graph, case["question"])
        results.append(
            RoutingResult(
                question_id=case["id"],
                expected_topics=case["expected_topics"],
                actual_topics=output["selected_topics"],
            )
        )

    summary = summarize(results)
    print(f"\nLevel 7 topic routing summary: {summary}")
    failures = [r.question_id for r in results if not r.is_correct]
    if failures:
        print(f"Failed questions: {failures}")

    assert summary["topic_accuracy"] >= MIN_TOPIC_ACCURACY, (
        f"Level 7 topic accuracy {summary['topic_accuracy']:.0%} is below the "
        f"{MIN_TOPIC_ACCURACY:.0%} target. Failed: {failures}"
    )


def test_level_7_overall_answer_accuracy(compiled_graph):
    """Suite-level synthesized-answer accuracy across every Level 7 question."""
    results = []
    for case in LEVEL_7_CASES:
        output = _invoke(compiled_graph, case["question"])
        all_retrieved_texts = [
            p["text"] for passages in output["retrieved_passages"].values() for p in passages
        ]
        results.append(
            AnswerResult(
                question_id=case["id"],
                actual_answer=output["final_answer"],
                expected_facts=case["expected_facts"],
                retrieved_texts=all_retrieved_texts,
                is_answerable=True,
            )
        )

    summary = summarize_answers(results)
    print(f"\nLevel 7 answer summary: {summary}")
    failures = [r.question_id for r in results if not r.is_correct]
    if failures:
        print(f"Failed questions: {failures}")

    assert summary["answer_accuracy"] >= MIN_ANSWER_ACCURACY, (
        f"Level 7 answer accuracy {summary['answer_accuracy']:.0%} is below the "
        f"{MIN_ANSWER_ACCURACY:.0%} target. Failed: {failures}"
    )
