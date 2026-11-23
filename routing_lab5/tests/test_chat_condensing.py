"""Chat-app tests: condensing-step accuracy.

Loads every conversation from `datasets/chat_ground_truth.jsonl` and
replays each one's turns in order through
`app.chat.graph.build_chat_graph()` (one shared thread_id per
conversation, via the session-scoped `compiled_chat_graph` fixture) - so
a later turn's `condense_question()` call sees a real
`conversation_history` built from the real pipeline's own prior answers,
not a hand-faked one. Each turn's condensed question is then checked
against that row's `expected_entities` - see
instructions/learnings/routing-lab3-chat-app-plan.md section 5.

Scored deterministically (substring presence of each expected entity in
the condensed question), not an LLM judge - consistent with every other
evaluation in this project.
"""

from __future__ import annotations

import re
import uuid

import pytest

from app.chat.condense import condense_question
from app.evaluation.condensing_metrics import CondensingResult, summarize_condensing
from tests.conftest import load_chat_ground_truth

CHAT_CONVERSATIONS = load_chat_ground_truth()
assert CHAT_CONVERSATIONS, "No conversations found in datasets/chat_ground_truth.jsonl"

MIN_CONDENSING_ACCURACY = 0.9


def _turn_id(conversation_id: str, turn: dict) -> str:
    return f"{conversation_id}-T{turn['turn']}"


def run_conversation(compiled_chat_graph, conversation_id: str, turns: list[dict]) -> list[CondensingResult]:
    """Replays one conversation's turns in order through the real chat
    graph, scoring each turn's condensed question as it goes."""
    thread_id = f"test-{conversation_id}-{uuid.uuid4()}"
    config = {"configurable": {"thread_id": thread_id}}
    results = []

    for turn in turns:
        output = compiled_chat_graph.invoke({"user_message": turn["user_message"]}, config=config)
        results.append(
            CondensingResult(
                question_id=_turn_id(conversation_id, turn),
                requires_context=turn["requires_context"],
                expected_entities=turn["expected_entities"],
                condensed_question=output["self_contained_question"],
            )
        )
    return results


@pytest.mark.parametrize("conversation_id", sorted(CHAT_CONVERSATIONS), ids=sorted(CHAT_CONVERSATIONS))
def test_conversation_turns_condense_correctly(compiled_chat_graph, conversation_id):
    """Every turn in this conversation must condense to a self-contained
    question containing all of that turn's expected entities."""
    turns = CHAT_CONVERSATIONS[conversation_id]
    results = run_conversation(compiled_chat_graph, conversation_id, turns)

    failures = [r for r in results if not r.is_correct]
    assert not failures, (
        f"{conversation_id}: condensing failed for "
        f"{[(r.question_id, r.expected_entities, r.condensed_question) for r in failures]}"
    )


def test_overall_condensing_accuracy(compiled_chat_graph):
    """Suite-level condensing accuracy across every conversation's turns."""
    all_results: list[CondensingResult] = []
    for conversation_id, turns in CHAT_CONVERSATIONS.items():
        all_results.extend(run_conversation(compiled_chat_graph, conversation_id, turns))

    summary = summarize_condensing(all_results)
    print(f"\nCondensing accuracy summary: {summary}")
    failures = [r.question_id for r in all_results if not r.is_correct]
    if failures:
        print(f"Failed turns: {failures}")

    assert summary["condensing_accuracy"] >= MIN_CONDENSING_ACCURACY, (
        f"Condensing accuracy {summary['condensing_accuracy']:.0%} is below the "
        f"{MIN_CONDENSING_ACCURACY:.0%} target. Failed: {failures}"
    )


@pytest.fixture
def switched_product_history():
    exchanges = [
        ("How long is the Eco 50 cycle on the DW-400 dishwasher?", "It takes 3 hours and 10 minutes."),
        ("What about Intensive 70 and Quick 45?", "Those are also DW-400 dishwasher cycles."),
        ("How often should I clean its spray arms?", "Check and clean the DW-400 spray arms regularly."),
        ("What features does the DW-400 dishwasher have?", "The DW-400 has several wash cycles."),
        ("List the DW-400 dishwasher cycle names.", "They include Eco 50 and Quick 45."),
        ("What does error E21 mean on the SmartHome WM-500?", "E21 indicates a drainage problem."),
    ]
    return [
        {
            "user_message": question,
            "self_contained_question": question,
            "final_answer": answer,
            "routing_summary": {},
            "attachments": [],
        }
        for question, answer in exchanges
    ]


def test_followup_after_product_switch_routes_and_answers_for_current_product(
    compiled_chat_graph, switched_product_history
):
    output = compiled_chat_graph.invoke(
        {
            "conversation_history": switched_product_history,
            "user_message": "What is its standard warranty term?",
            "attachments": [],
        },
        config={"configurable": {"thread_id": f"test-product-switch-{uuid.uuid4()}"}},
    )

    question = output["self_contained_question"]
    assert "WM-500" in question and "DW-400" not in question, question
    assert output["routing_result"]["selected_subtopics"].get("appliances") == "washing_machines"
    answer = output["final_answer"]
    assert re.search(r"\b(?:2|two)[ -]+years?\b", answer, re.IGNORECASE), answer
    assert "DW-400" not in answer, answer


@pytest.mark.parametrize(
    ("message", "expected", "unexpected"),
    [
        ("What is the DW-400's standard warranty term?", "DW-400", ("WM-500",)),
        ("What about the dishwasher's standard warranty term?", "DW-400", ("WM-500",)),
        ("How long does a typical home loan last?", "loan", ("WM-500", "DW-400")),
    ],
)
def test_followup_can_refer_to_earlier_product_or_change_topic(
    switched_product_history, message, expected, unexpected
):
    question = condense_question(switched_product_history, message).self_contained_question
    assert expected.lower() in question.lower(), question
    assert all(entity not in question for entity in unexpected), question
