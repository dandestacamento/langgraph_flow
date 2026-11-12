"""Shared state definition for the Routing Accuracy Lab's LangGraph workflow.

A single TypedDict (`RoutingState`) is threaded through every node. Each
router/agent node only returns the keys it actually sets; LangGraph merges
those into the running state. `execution_log` accumulates a structured
trace of every node that ran, which `app/evaluation` and the Streamlit
dashboard replay after a run to score and visualize routing accuracy
against `datasets/routing_ground_truth.jsonl`.

Level 1 only ever selects a single topic (`selected_topics` has length 1)
and runs a single agent. `agent_responses` is still a dict keyed by topic
and `selected_topics` is still a list so the same graph shape extends to
Level 7 (multi-topic parallel routing) without a rewrite.

Level 2 adds subtopic routing: one subtopic decision per selected topic,
keyed by topic in `subtopic_decisions`/`selected_subtopics` for the same
multi-topic-ready reason `agent_responses` is keyed by topic.
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

Topic = Literal[
    "appliances",
    "azure_cloud",
    "data_engineering",
    "python",
    "finance",
    "customer_support",
]

Complexity = Literal["simple", "intermediate", "complex"]


def merge_dicts(left: dict, right: dict) -> dict:
    """Reducer that merges two dicts so parallel agent branches can each
    write their own key into `agent_responses` without clobbering each other."""
    return {**left, **right}


class ComplexityDecision(TypedDict):
    complexity: Complexity
    confidence: float
    reasoning: str


class TopicDecision(TypedDict):
    topics: list[Topic]
    confidence: float
    reasoning: str


class SubtopicDecision(TypedDict):
    subtopic: str
    confidence: float
    reasoning: str


class RoutingState(TypedDict):
    # Input
    question: str

    # Stage 1 (complexity_router): simple/intermediate/complex classification.
    complexity_decision: ComplexityDecision | None

    # Stage 2 (topic_router): one or more topics the question belongs to.
    topic_decision: TopicDecision | None
    selected_topics: list[Topic]

    # Stage 2b (subtopic_router): one subtopic decision per selected topic.
    subtopic_decisions: Annotated[dict[str, SubtopicDecision], merge_dicts]
    selected_subtopics: Annotated[dict[str, str], merge_dicts]

    # One entry per topic agent that ran, merged via reducer so multiple
    # agents can run in parallel (Level 7+) without overwriting each other.
    agent_responses: Annotated[dict[str, str], merge_dicts]

    # Final answer surfaced to the user (identical to the single agent
    # response until the synthesis agent does real multi-topic merging).
    final_answer: str

    # Execution trace: list of {"node", "action", "output", "duration_ms"}
    # dicts, used by evaluation/routing_metrics.py and the dashboard.
    execution_log: Annotated[list[dict], operator.add]
