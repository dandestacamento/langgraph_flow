"""Level 6 tests: multi-chapter evidence aggregation.

Loads every Level 6 question from datasets/routing_ground_truth.jsonl, runs
it through the full graph, and checks two independent things, mirroring the
Level 4 pattern but generalized to compound questions that need evidence
from TWO chapters within the same subtopic (e.g. "what does E21 mean on
the WM-500, and is the repair covered under warranty?" - the fault-code
chapter alone is not enough, see
instructions/Langgraph_routing/4_to_5_obserability.md):

1. Retrieval: did ALL expected chapters appear among the top-k passages
   retrieved for the question (multi-chapter coverage), not just one?
2. Answer: does the agent's final answer contain the expected facts from
   BOTH chapters, proving the answer actually aggregates evidence rather
   than only reporting whichever chapter dominated retrieval?

Both are scored with deterministic checks (chapter_id membership,
substring matching), not an LLM judge - consistent with Levels 1-4.
"""

from __future__ import annotations

import pytest

from app.evaluation.answer_metrics import AnswerResult, answer_correctness, summarize_answers
from app.evaluation.retrieval_metrics import (
    MultiChapterRetrievalResult,
    summarize_multichapter_retrieval,
)
from app.state import initial_state
from scripts.run_batch_tests import DATASET_PATH, load_questions, score_case
from tests.conftest import load_ground_truth

LEVEL_6_CASES = load_ground_truth(level=6)
assert LEVEL_6_CASES, "No Level 6 cases found in datasets/routing_ground_truth.jsonl"

MIN_MULTICHAPTER_COVERAGE = 0.9
MIN_ANSWER_ACCURACY = 0.85


@pytest.mark.parametrize(
    ("answer", "expected_score"),
    [
        ("A drainage problem; the warranty is 2 years.", 1.0),
        ("A drainage problem; the warranty is two years.", 1.0),
        ("A drainage problem; the warranty is 2-year.", 1.0),
        ("A drainage problem; the warranty is 12 years.", 0.5),
        ("A drainage problem; the warranty is 12-year.", 0.5),
        ("A drainage problem; the warranty is twenty two years.", 0.5),
        ("A drainage problem; the warranty is one hundred and two years.", 0.5),
        ("A drainage problem; the warranty is 2.5 years.", 0.5),
        ("A drainage problem; the warranty is 2 months.", 0.5),
        ("The warranty is 2 years.", 0.5),
    ],
)
def test_year_duration_answer_facts(answer, expected_score):
    assert answer_correctness(answer, ["drainage", "2-year"]) == expected_score


def test_t016_batch_scoring_accepts_correct_answer():
    case = load_questions(DATASET_PATH, ["T016"])[0]
    output = {
        "selected_topics": ["appliances"],
        "selected_subtopics": {"appliances": "washing_machines"},
        "retrieved_passages": {
            "appliances": [
                {"chapter_id": "chapter_03_faults", "text": "E21 is a drainage problem."},
                {"chapter_id": "chapter_01_types", "text": "WM-500: 2-year standard warranty."},
            ]
        },
        "final_answer": "E21 indicates a drainage problem. The WM-500 has a standard warranty of 2 years.",
    }

    scores = score_case(case, output)
    assert scores["routing_correct"] is True
    assert scores["answer_correct"] is True
    assert scores["overall_correct"] is True


def _invoke(compiled_graph, question: str) -> dict:
    return compiled_graph.invoke(initial_state(question))


@pytest.mark.parametrize("case", LEVEL_6_CASES, ids=[c["id"] for c in LEVEL_6_CASES])
def test_all_expected_chapters_are_recalled(compiled_graph, case):
    """Every chapter the compound question needs evidence from must appear
    among the retrieved passages, not just the single most dominant one."""
    output = _invoke(compiled_graph, case["question"])
    expected_topic = case["expected_topics"][0]
    retrieved = output["retrieved_passages"].get(expected_topic, [])
    retrieved_chapter_ids = [p["chapter_id"] for p in retrieved]

    missing = set(case["expected_chapters"]) - set(retrieved_chapter_ids)
    assert not missing, (
        f"{case['id']}: missing expected chapters {missing} among retrieved "
        f"chapters {retrieved_chapter_ids} (question: {case['question']!r})"
    )


@pytest.mark.parametrize("case", LEVEL_6_CASES, ids=[c["id"] for c in LEVEL_6_CASES])
def test_answer_combines_facts_from_both_chapters(compiled_graph, case):
    """The agent's final answer must contain every expected fact, spanning
    both chapters, proving the answer actually aggregates evidence."""
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


def test_level_6_overall_multichapter_coverage(compiled_graph):
    """Suite-level multi-chapter coverage across every Level 6 question."""
    results = []
    for case in LEVEL_6_CASES:
        output = _invoke(compiled_graph, case["question"])
        expected_topic = case["expected_topics"][0]
        retrieved = output["retrieved_passages"].get(expected_topic, [])
        results.append(
            MultiChapterRetrievalResult(
                question_id=case["id"],
                expected_chapters=case["expected_chapters"],
                retrieved_chapter_ids=[p["chapter_id"] for p in retrieved],
            )
        )

    summary = summarize_multichapter_retrieval(results)
    print(f"\nLevel 6 multi-chapter retrieval summary: {summary}")
    failures = [r.question_id for r in results if not r.is_fully_covered]
    if failures:
        print(f"Incomplete coverage: {failures}")

    assert summary["multichapter_coverage"] >= MIN_MULTICHAPTER_COVERAGE, (
        f"Level 6 multi-chapter coverage {summary['multichapter_coverage']:.0%} is below the "
        f"{MIN_MULTICHAPTER_COVERAGE:.0%} target. Failed: {failures}"
    )


def test_level_6_overall_answer_accuracy(compiled_graph):
    """Suite-level answer accuracy across every Level 6 compound question."""
    results = []
    for case in LEVEL_6_CASES:
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
    print(f"\nLevel 6 answer summary: {summary}")
    failures = [r.question_id for r in results if not r.is_correct]
    if failures:
        print(f"Failed questions: {failures}")

    assert summary["answer_accuracy"] >= MIN_ANSWER_ACCURACY, (
        f"Level 6 answer accuracy {summary['answer_accuracy']:.0%} is below the "
        f"{MIN_ANSWER_ACCURACY:.0%} target. Failed: {failures}"
    )
