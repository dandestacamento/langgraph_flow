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


@dataclass
class SubtopicRoutingResult:
    """One scored Level 2 test case: expected vs. actual (topic, subtopic)
    for a single question.

    Correctness requires both the topic and the subtopic to match. A
    wrong topic selection always counts as wrong here too - subtopic
    routing is defined as narrowing an already-correct topic down
    further, per instructions/Langgraph_routing/2_routing_scenarios.md
    (Level 2: "Correct subtopic selection")."""

    question_id: str
    expected_topic: str
    expected_subtopic: str
    actual_topics: list[str]
    actual_subtopics: dict[str, str]
    is_correct: bool = field(init=False)

    def __post_init__(self) -> None:
        actual_subtopic = self.actual_subtopics.get(self.expected_topic)
        self.is_correct = (
            self.expected_topic in self.actual_topics
            and actual_subtopic == self.expected_subtopic
        )


def subtopic_accuracy(results: list[SubtopicRoutingResult]) -> float:
    """Fraction of test cases where both topic and subtopic were selected
    correctly. Returns 0.0 for an empty result list."""
    if not results:
        return 0.0
    return sum(1 for r in results if r.is_correct) / len(results)


def summarize_subtopic(results: list[SubtopicRoutingResult]) -> dict[str, float | int]:
    """One-stop summary dict for Level 2 test reports."""
    return {
        "total": len(results),
        "correct": sum(1 for r in results if r.is_correct),
        "subtopic_accuracy": round(subtopic_accuracy(results), 4),
    }


@dataclass
class ChapterRoutingResult:
    """One scored Level 3 test case: expected vs. actual (topic, subtopic,
    chapter_id) for a single question.

    Correctness requires the topic, subtopic, and chapter to all match - a
    wrong topic or subtopic selection always counts as wrong here too,
    same reasoning as SubtopicRoutingResult one level up (Level 3: "Correct
    chapter identification", per
    instructions/Langgraph_routing/2_routing_scenarios.md)."""

    question_id: str
    expected_topic: str
    expected_subtopic: str
    expected_chapter: str
    actual_topics: list[str]
    actual_subtopics: dict[str, str]
    actual_chapters: dict[str, str]
    is_correct: bool = field(init=False)

    def __post_init__(self) -> None:
        actual_subtopic = self.actual_subtopics.get(self.expected_topic)
        actual_chapter = self.actual_chapters.get(self.expected_topic)
        self.is_correct = (
            self.expected_topic in self.actual_topics
            and actual_subtopic == self.expected_subtopic
            and actual_chapter == self.expected_chapter
        )


def chapter_accuracy(results: list[ChapterRoutingResult]) -> float:
    """Fraction of test cases where topic, subtopic, and chapter were all
    selected correctly. Returns 0.0 for an empty result list."""
    if not results:
        return 0.0
    return sum(1 for r in results if r.is_correct) / len(results)


def summarize_chapter(results: list[ChapterRoutingResult]) -> dict[str, float | int]:
    """One-stop summary dict for Level 3 test reports."""
    return {
        "total": len(results),
        "correct": sum(1 for r in results if r.is_correct),
        "chapter_accuracy": round(chapter_accuracy(results), 4),
    }


@dataclass
class ClarificationResult:
    """One scored Level 5 test case: did the system correctly decide
    whether to ask a clarifying question or answer directly?

    `actual_behavior` should be derived from the execution trace (see
    `app.observability.execution_logger.get_node_sequence`) rather than
    inspecting `final_answer` text, since "did clarification_agent run"
    is the deterministic signal - checking the answer text for something
    that "looks like a question" would be unreliable."""

    question_id: str
    expected_behavior: str  # "clarify" or "answer"
    actual_behavior: str  # "clarify" or "answer"
    is_correct: bool = field(init=False)

    def __post_init__(self) -> None:
        self.is_correct = self.expected_behavior == self.actual_behavior


def clarification_accuracy(results: list[ClarificationResult]) -> float:
    """Fraction of test cases where the clarify-vs-answer decision matched
    the expected behavior. Returns 0.0 for an empty result list."""
    if not results:
        return 0.0
    return sum(1 for r in results if r.is_correct) / len(results)


def summarize_clarification(results: list[ClarificationResult]) -> dict[str, float | int]:
    """One-stop summary dict for Level 5 test reports."""
    return {
        "total": len(results),
        "correct": sum(1 for r in results if r.is_correct),
        "clarification_accuracy": round(clarification_accuracy(results), 4),
    }


@dataclass
class ToolSelectionResult:
    """One scored Level 8 test case: did the Tool Router make the
    correct tool decision for one topic?

    `expected_tool` is `None` for a question that should be answered from
    retrieved passages alone (`needs_tool=False`) - matching that
    correctly (not just picking the right tool name when one IS needed)
    is just as important a part of Level 8 accuracy, since an
    unnecessary tool call is itself a routing mistake (see the
    "Efficiency" evaluation question in
    instructions/Langgraph_routing/1_architecture.md: "did the system use
    the minimum necessary agents and tools?")."""

    question_id: str
    expected_tool: str | None
    actual_needs_tool: bool
    actual_tool: str | None
    is_correct: bool = field(init=False)

    def __post_init__(self) -> None:
        if self.expected_tool is None:
            self.is_correct = not self.actual_needs_tool
        else:
            self.is_correct = self.actual_needs_tool and self.actual_tool == self.expected_tool


def tool_selection_accuracy(results: list[ToolSelectionResult]) -> float:
    """Fraction of test cases where the tool decision (including
    correctly deciding no tool was needed) matched expected. Returns 0.0
    for an empty result list."""
    if not results:
        return 0.0
    return sum(1 for r in results if r.is_correct) / len(results)


def summarize_tool_selection(results: list[ToolSelectionResult]) -> dict[str, float | int]:
    """One-stop summary dict for Level 8 test reports."""
    return {
        "total": len(results),
        "correct": sum(1 for r in results if r.is_correct),
        "tool_selection_accuracy": round(tool_selection_accuracy(results), 4),
    }


@dataclass
class MultiHopResult:
    """One scored Level 9 test case: did the Multi-Hop Router make the
    correct is_multi_hop decision, and - when it genuinely is multi-hop -
    did hop 1 resolve to the expected value?

    `expected_hop1_fact` is `None` for the regression-check questions
    (should NOT be flagged multi-hop) - matching that correctly, not just
    detecting genuine multi-hop cases, is part of Level 9 accuracy for
    the same "efficiency" reason as `ToolSelectionResult.expected_tool`
    above: treating an ordinary question as multi-hop would trigger two
    extra full pipeline invocations for no reason."""

    question_id: str
    expected_is_multi_hop: bool
    expected_hop1_fact: str | None
    actual_is_multi_hop: bool
    actual_hop1_value: str | None
    is_correct: bool = field(init=False)

    def __post_init__(self) -> None:
        if not self.expected_is_multi_hop:
            self.is_correct = not self.actual_is_multi_hop
        elif not self.actual_is_multi_hop:
            self.is_correct = False
        elif self.expected_hop1_fact is None or self.actual_hop1_value is None:
            self.is_correct = True
        else:
            self.is_correct = self.expected_hop1_fact.lower() in self.actual_hop1_value.lower()


def multihop_accuracy(results: list[MultiHopResult]) -> float:
    """Fraction of test cases where the multi-hop decision (and, when
    applicable, hop 1's resolved value) matched expected. Returns 0.0 for
    an empty result list."""
    if not results:
        return 0.0
    return sum(1 for r in results if r.is_correct) / len(results)


def summarize_multihop(results: list[MultiHopResult]) -> dict[str, float | int]:
    """One-stop summary dict for Level 9 test reports."""
    return {
        "total": len(results),
        "correct": sum(1 for r in results if r.is_correct),
        "multihop_accuracy": round(multihop_accuracy(results), 4),
    }
