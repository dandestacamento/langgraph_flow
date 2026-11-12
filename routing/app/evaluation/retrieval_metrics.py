"""Retrieval accuracy metrics (Level 4 - RAG retrieval).

Deterministic, per instructions/Langgraph_routing/4_to_5_obserability.md:
"Retrieval Recall@K: Did the correct supporting passages appear in the top
K results?" - scored by exact chapter_id membership, not an LLM judge.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RetrievalResult:
    """One scored Level 4 test case: did the expected chapter appear
    anywhere among the top-k retrieved passages for a question?

    `expected_chapter` is `None` for deliberately unanswerable questions
    (see `datasets/routing_ground_truth.jsonl` Level 4 entries with
    `"is_answerable": false`) - those are excluded from recall scoring
    here and checked separately via `answer_metrics.is_insufficient_info`."""

    question_id: str
    expected_chapter: str | None
    retrieved_chapter_ids: list[str]
    is_recalled: bool = field(init=False)

    def __post_init__(self) -> None:
        self.is_recalled = self.expected_chapter is not None and (
            self.expected_chapter in self.retrieved_chapter_ids
        )


def retrieval_recall_at_k(results: list[RetrievalResult]) -> float:
    """Fraction of answerable test cases whose expected chapter appeared
    among the top-k retrieved chapters. Returns 0.0 if there are no
    answerable cases (expected_chapter is not None) to score."""
    answerable = [r for r in results if r.expected_chapter is not None]
    if not answerable:
        return 0.0
    return sum(1 for r in answerable if r.is_recalled) / len(answerable)


def summarize_retrieval(results: list[RetrievalResult]) -> dict[str, float | int]:
    """One-stop summary dict for Level 4 retrieval test reports."""
    answerable = [r for r in results if r.expected_chapter is not None]
    return {
        "total": len(answerable),
        "recalled": sum(1 for r in answerable if r.is_recalled),
        "recall_at_k": round(retrieval_recall_at_k(results), 4),
    }
