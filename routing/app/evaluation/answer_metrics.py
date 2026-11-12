"""Answer accuracy/groundedness metrics: Level 4+ (RAG retrieval and
beyond). Not yet implemented - needs retrieved evidence to check answers
against, plus `datasets/answer_ground_truth.jsonl` with verified facts.
"""

from __future__ import annotations


def answer_correctness(actual_answer: str, expected_facts: list[str]) -> float:
    raise NotImplementedError(
        "Answer accuracy metrics are implemented starting at Level 4 (see "
        "instructions/Langgraph_routing/4_to_5_obserability.md)."
    )


def groundedness(actual_answer: str, retrieved_passages: list[str]) -> float:
    raise NotImplementedError(
        "Groundedness metrics are implemented starting at Level 4 (see "
        "instructions/Langgraph_routing/4_to_5_obserability.md)."
    )
