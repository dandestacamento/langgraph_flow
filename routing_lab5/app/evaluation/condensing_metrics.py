"""Condensing-step accuracy metrics (routing-lab3 chat application).

Deterministic, consistent with every other metric in `app/evaluation/`:
checked by substring presence, not an LLM judge - see
instructions/learnings/routing-lab3-chat-app-plan.md section 5.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CondensingResult:
    """One scored chat-app test case: did
    `app.chat.condense.condense_question()` correctly resolve a turn's
    self-contained question?

    For a context-dependent turn (`requires_context=True`), correctness
    means every entity in `expected_entities` (e.g. a model number, fault
    code, or named policy term) appears - case-insensitive substring - in
    the condensed question, proving an ambiguous reference ("it", "that
    repair", "instead") was actually resolved rather than left unresolved
    or dropped.

    For a turn that's already self-contained (`requires_context=False`),
    `expected_entities` instead lists terms the ORIGINAL message itself
    already contains - correctness here means condensing didn't
    erroneously drag in irrelevant prior-turn context or otherwise lose
    those terms, i.e. it left an already-fine question alone."""

    question_id: str
    requires_context: bool
    expected_entities: list[str]
    condensed_question: str
    is_correct: bool = field(init=False)

    def __post_init__(self) -> None:
        condensed_lower = self.condensed_question.lower()
        self.is_correct = all(entity.lower() in condensed_lower for entity in self.expected_entities)


def condensing_accuracy(results: list[CondensingResult]) -> float:
    """Fraction of turns whose condensed question contained every
    expected entity. Returns 0.0 for an empty result list."""
    if not results:
        return 0.0
    return sum(1 for r in results if r.is_correct) / len(results)


def summarize_condensing(results: list[CondensingResult]) -> dict[str, float | int]:
    """One-stop summary dict for chat-app condensing test reports."""
    return {
        "total": len(results),
        "correct": sum(1 for r in results if r.is_correct),
        "condensing_accuracy": round(condensing_accuracy(results), 4),
    }
