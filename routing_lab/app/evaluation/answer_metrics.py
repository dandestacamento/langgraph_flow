"""Answer accuracy/groundedness metrics (Level 4 - RAG retrieval).

Deterministic by design, per instructions/Langgraph_routing/4_to_5_obserability.md:
"Use deterministic assertions for routes, document IDs, tool calls,
calculations, and known facts. An LLM judge can supplement these checks
for nuanced answers" - no LLM judge is used here; these are substring and
lexical-overlap checks, not semantic similarity.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.agents._shared import INSUFFICIENT_INFO_MARKER


def answer_correctness(actual_answer: str, expected_facts: list[str]) -> float:
    """Fraction of `expected_facts` substrings (case-insensitive) found
    anywhere in `actual_answer`. A deterministic fact-presence check, not
    a semantic similarity score - each `expected_facts` entry should be a
    short, specific, unambiguous substring (e.g. "E42", "door lock").
    Returns 1.0 for an empty `expected_facts` list (nothing to check)."""
    if not expected_facts:
        return 1.0
    answer_lower = actual_answer.lower()
    found = sum(1 for fact in expected_facts if fact.lower() in answer_lower)
    return found / len(expected_facts)


def groundedness(actual_answer: str, retrieved_passages: list[str]) -> float:
    """Crude deterministic groundedness proxy: the fraction of the
    answer's distinctive words (alphabetic, length > 4, to skip common
    short words) that also appear somewhere in the retrieved passage
    text. This is a lexical-overlap check, not semantic entailment - it
    catches answers that introduce facts absent from anything retrieved,
    but can't catch subtler unsupported claims built from words that do
    appear in the passages. An LLM judge is the natural supplement for
    that, per the module docstring above, and can be added later without
    changing this function's contract.

    Returns 0.0 if nothing was retrieved (nothing to be grounded in)."""
    if not retrieved_passages:
        return 0.0
    combined = " ".join(retrieved_passages).lower()
    words = {
        w.strip(".,:;()[]'\"")
        for w in actual_answer.lower().split()
        if len(w) > 4 and w.strip(".,:;()[]'\"").isalpha()
    }
    if not words:
        return 1.0
    supported = sum(1 for w in words if w in combined)
    return supported / len(words)


def is_insufficient_info(actual_answer: str, marker: str) -> bool:
    """Whether an agent's answer declined to answer (reported insufficient
    information) rather than fabricating a response. `marker` should be
    `app.agents._shared.INSUFFICIENT_INFO_MARKER`."""
    return marker.lower() in actual_answer.lower()


@dataclass
class AnswerResult:
    """One scored Level 4 answer-quality test case."""

    question_id: str
    actual_answer: str
    expected_facts: list[str]
    retrieved_texts: list[str]
    is_answerable: bool
    correctness: float = field(init=False)
    groundedness_score: float = field(init=False)
    is_correct: bool = field(init=False)

    def __post_init__(self) -> None:
        marker_present = is_insufficient_info(self.actual_answer, INSUFFICIENT_INFO_MARKER)
        if not self.is_answerable:
            # Deliberately unanswerable question: correct iff the agent
            # declined instead of fabricating an answer.
            self.correctness = 1.0 if marker_present else 0.0
            self.groundedness_score = 1.0 if marker_present else 0.0
            self.is_correct = marker_present
            return

        if marker_present:
            # Answerable question the agent incorrectly declined.
            self.correctness = 0.0
            self.groundedness_score = 0.0
            self.is_correct = False
            return

        self.correctness = answer_correctness(self.actual_answer, self.expected_facts)
        self.groundedness_score = groundedness(self.actual_answer, self.retrieved_texts)
        self.is_correct = self.correctness >= 0.99


def summarize_answers(results: list[AnswerResult]) -> dict[str, float | int]:
    """One-stop summary dict for Level 4 answer-quality test reports."""
    if not results:
        return {"total": 0, "correct": 0, "answer_accuracy": 0.0, "avg_groundedness": 0.0}
    return {
        "total": len(results),
        "correct": sum(1 for r in results if r.is_correct),
        "answer_accuracy": round(sum(1 for r in results if r.is_correct) / len(results), 4),
        "avg_groundedness": round(sum(r.groundedness_score for r in results) / len(results), 4),
    }
