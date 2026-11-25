"""Answer accuracy/groundedness metrics (Level 4 - RAG retrieval).

Deterministic by design, per instructions/Langgraph_routing/4_to_5_obserability.md:
"Use deterministic assertions for routes, document IDs, tool calls,
calculations, and known facts. An LLM judge can supplement these checks
for nuanced answers" - no LLM judge is used here; these are substring and
lexical-overlap checks, not semantic similarity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.agents._shared import INSUFFICIENT_INFO_MARKER, UNVERIFIED_ANSWER_MARKER

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_YEAR_DURATION = re.compile(
    r"(?<![\w.-])(?P<number>\d+|one|two|three|four|five|six|seven|eight|nine|ten)"
    r"(?:\s*-\s*|\s+)years?\b",
    re.IGNORECASE,
)
_COMPOUND_NUMBER_PREFIX = re.compile(
    r"\b(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand)"
    r"[\s-]+(?:and\s+)?$",
    re.IGNORECASE,
)


def _year_value(match: re.Match[str]) -> int:
    number = match.group("number").lower()
    return int(number) if number.isdigit() else _NUMBER_WORDS[number]


def answer_correctness(actual_answer: str, expected_facts: list[str]) -> float:
    """Fraction of expected facts found in the answer, case-insensitively.
    Standalone year durations also match equivalent number/word and
    hyphenated/plural forms. A deterministic fact-presence check, not
    a semantic similarity score - each `expected_facts` entry should be a
    short, specific, unambiguous substring (e.g. "E42", "door lock").
    Returns 1.0 for an empty `expected_facts` list (nothing to check)."""
    if not expected_facts:
        return 1.0
    answer_lower = actual_answer.lower()
    found = 0
    for fact in expected_facts:
        duration = _YEAR_DURATION.fullmatch(fact.strip())
        if duration:
            found += any(
                _year_value(candidate) == _year_value(duration)
                and not _COMPOUND_NUMBER_PREFIX.search(answer_lower[:candidate.start()])
                for candidate in _YEAR_DURATION.finditer(answer_lower)
            )
        else:
            found += fact.lower() in answer_lower
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
    """Whether the agent declined for insufficient information or an unverified answer.

    `marker` should be `app.agents._shared.INSUFFICIENT_INFO_MARKER`.
    """
    return marker.lower() in actual_answer.lower() or UNVERIFIED_ANSWER_MARKER.lower() in actual_answer.lower()


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
