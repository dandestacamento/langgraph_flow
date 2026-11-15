"""Level 4 tests: RAG retrieval.

Loads every Level 4 question from datasets/routing_ground_truth.jsonl, runs
it through the full graph, and checks two independent things per the five
evaluation questions in instructions/Langgraph_routing/1_architecture.md:

1. Retrieval: did the expected chapter appear among the top-k passages
   retrieved for the question (Retrieval Recall@K)?
2. Answer: for answerable questions, does the agent's answer contain the
   expected facts, grounded in what was actually retrieved; for
   deliberately unanswerable questions, does the agent correctly report
   insufficient information instead of fabricating an answer?

Both are scored with deterministic checks (chapter_id membership,
substring/lexical-overlap matching), not an LLM judge - consistent with
Levels 1-3.
"""

from __future__ import annotations

import pytest

from app.evaluation.answer_metrics import AnswerResult, summarize_answers
from app.evaluation.retrieval_metrics import RetrievalResult, summarize_retrieval
from app.state import initial_state
from tests.conftest import load_ground_truth

LEVEL_4_CASES = load_ground_truth(level=4)
assert LEVEL_4_CASES, "No Level 4 cases found in datasets/routing_ground_truth.jsonl"

ANSWERABLE_CASES = [c for c in LEVEL_4_CASES if c["is_answerable"]]
UNANSWERABLE_CASES = [c for c in LEVEL_4_CASES if not c["is_answerable"]]

MIN_RECALL_AT_K = 0.9
MIN_ANSWER_ACCURACY = 0.85


def _invoke(compiled_graph, question: str) -> dict:
    return compiled_graph.invoke(initial_state(question))


@pytest.mark.parametrize("case", ANSWERABLE_CASES, ids=[c["id"] for c in ANSWERABLE_CASES])
def test_expected_chapter_is_recalled(compiled_graph, case):
    """The expected chapter must appear among the retrieved passages for
    its topic (Retrieval Recall@K, scored at k=app.config.RETRIEVAL_TOP_K)."""
    output = _invoke(compiled_graph, case["question"])
    expected_topic = case["expected_topics"][0]
    retrieved = output["retrieved_passages"].get(expected_topic, [])
    retrieved_chapter_ids = [p["chapter_id"] for p in retrieved]

    assert case["expected_chapter"] in retrieved_chapter_ids, (
        f"{case['id']}: expected chapter {case['expected_chapter']!r} not among retrieved "
        f"chapters {retrieved_chapter_ids} (question: {case['question']!r})"
    )


@pytest.mark.parametrize("case", ANSWERABLE_CASES, ids=[c["id"] for c in ANSWERABLE_CASES])
def test_answerable_question_produces_correct_grounded_answer(compiled_graph, case):
    """For an answerable question, the agent's final answer must contain
    every expected fact and must not decline to answer."""
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


@pytest.mark.parametrize("case", UNANSWERABLE_CASES, ids=[c["id"] for c in UNANSWERABLE_CASES])
def test_unanswerable_question_reports_insufficient_information(compiled_graph, case):
    """For a deliberately unanswerable question, the agent must decline
    rather than fabricate an answer from unrelated retrieved passages."""
    output = _invoke(compiled_graph, case["question"])
    expected_topic = case["expected_topics"][0]
    answer = output["agent_responses"].get(expected_topic, "")
    retrieved_texts = [p["text"] for p in output["retrieved_passages"].get(expected_topic, [])]

    result = AnswerResult(
        question_id=case["id"],
        actual_answer=answer,
        expected_facts=[],
        retrieved_texts=retrieved_texts,
        is_answerable=False,
    )
    assert result.is_correct, (
        f"{case['id']}: expected an insufficient-information response, but the agent "
        f"answered: {answer!r}"
    )


def test_level_4_overall_retrieval_recall(compiled_graph):
    """Suite-level Retrieval Recall@K across every answerable Level 4 question."""
    results = []
    for case in ANSWERABLE_CASES:
        output = _invoke(compiled_graph, case["question"])
        expected_topic = case["expected_topics"][0]
        retrieved = output["retrieved_passages"].get(expected_topic, [])
        results.append(
            RetrievalResult(
                question_id=case["id"],
                expected_chapter=case["expected_chapter"],
                retrieved_chapter_ids=[p["chapter_id"] for p in retrieved],
            )
        )

    summary = summarize_retrieval(results)
    print(f"\nLevel 4 retrieval summary: {summary}")
    failures = [r.question_id for r in results if not r.is_recalled]
    if failures:
        print(f"Failed to recall: {failures}")

    assert summary["recall_at_k"] >= MIN_RECALL_AT_K, (
        f"Level 4 Retrieval Recall@K {summary['recall_at_k']:.0%} is below the "
        f"{MIN_RECALL_AT_K:.0%} target. Failed: {failures}"
    )


def test_level_4_overall_answer_accuracy(compiled_graph):
    """Suite-level answer accuracy across every Level 4 question (answerable
    and deliberately unanswerable combined)."""
    results = []
    for case in LEVEL_4_CASES:
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
    print(f"\nLevel 4 answer summary: {summary}")
    failures = [r.question_id for r in results if not r.is_correct]
    if failures:
        print(f"Failed questions: {failures}")

    assert summary["answer_accuracy"] >= MIN_ANSWER_ACCURACY, (
        f"Level 4 answer accuracy {summary['answer_accuracy']:.0%} is below the "
        f"{MIN_ANSWER_ACCURACY:.0%} target. Failed: {failures}"
    )
