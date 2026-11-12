"""Deterministic routing accuracy metrics.

Per instructions/Langgraph_routing/4_to_5_obserability.md, routing
correctness is scored with deterministic assertions (exact topic/route
matches), not by asking an LLM to judge another LLM. These functions are
pure and side-effect free so they can be unit tested on their own and
reused by both pytest (Level 1+) and the Streamlit dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RoutingResult:
    """One scored test case: expected vs. actual topic(s) for a single question."""

    question_id: str
    expected_topics: list[str]
    actual_topics: list[str]
    is_correct: bool = field(init=False)

    def __post_init__(self) -> None:
        # Level 1: exact-set match. A question with one expected topic is
        # only correct if the router selected that topic and no others.
        self.is_correct = set(self.expected_topics) == set(self.actual_topics)


def topic_accuracy(results: list[RoutingResult]) -> float:
    """Fraction of test cases where the actual topic set exactly matches
    the expected topic set. Returns 0.0 for an empty result list."""
    if not results:
        return 0.0
    return sum(1 for r in results if r.is_correct) / len(results)


def route_precision_recall_f1(results: list[RoutingResult]) -> dict[str, float]:
    """Micro-averaged precision/recall/F1 treating each (question, topic)
    pair as a classification decision. Useful from Level 7 onward, once
    questions can have more than one expected topic - with Level 1-style
    single-topic questions this reduces to plain accuracy."""
    true_positives = 0
    false_positives = 0
    false_negatives = 0

    for r in results:
        expected = set(r.expected_topics)
        actual = set(r.actual_topics)
        true_positives += len(expected & actual)
        false_positives += len(actual - expected)
        false_negatives += len(expected - actual)

    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) else 0.0
    recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return {"precision": precision, "recall": recall, "f1": f1}


def summarize(results: list[RoutingResult]) -> dict[str, float | int]:
    """One-stop summary dict for printing in a test report or dashboard panel."""
    metrics = route_precision_recall_f1(results)
    return {
        "total": len(results),
        "correct": sum(1 for r in results if r.is_correct),
        "topic_accuracy": round(topic_accuracy(results), 4),
        "precision": round(metrics["precision"], 4),
        "recall": round(metrics["recall"], 4),
        "f1": round(metrics["f1"], 4),
    }
