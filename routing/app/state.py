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

Level 3 adds chapter routing: one chapter decision per selected topic,
keyed by topic in `chapter_decisions`/`selected_chapters`, following the
same pattern.

Level 4 adds RAG retrieval: one list of retrieved passages per selected
topic, keyed by topic in `retrieved_passages`, scoped to that topic's
subtopic (not narrowed to the single chapter_selector guess - see
`app/rag/retrieval.py` for why) and consumed by the topic agents to
ground their answers instead of answering from the LLM's own knowledge.

Level 7 adds `TopicDecision.topic_questions`: for a multi-topic question,
a per-topic restatement containing only that topic's relevant part. Every
per-topic classifier/agent (`subtopic_router`, `chapter_selector`,
`rag_retriever`, and the topic agents) uses `get_topic_question()` below
instead of the raw `state["question"]`, so none of them ever sees another
topic's fragment (see `get_topic_question`'s docstring for why that's
more robust than instructing a classifier/agent to ignore text it can
still see).
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
    is_ambiguous: bool
    topic_questions: dict[str, str]
    confidence: float
    reasoning: str


class SubtopicDecision(TypedDict):
    subtopic: str
    confidence: float
    reasoning: str


class ChapterDecision(TypedDict):
    chapter_id: str
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

    # Stage 2c (chapter_selector): one chapter decision per selected topic.
    chapter_decisions: Annotated[dict[str, ChapterDecision], merge_dicts]
    selected_chapters: Annotated[dict[str, str], merge_dicts]

    # Stage 3 (rag_retriever): one list of retrieved passages per selected
    # topic, each a dict with text/chapter_id/document_id/subtopic/score.
    retrieved_passages: Annotated[dict[str, list[dict]], merge_dicts]

    # One entry per topic agent that ran, merged via reducer so multiple
    # agents can run in parallel (Level 7+) without overwriting each other.
    agent_responses: Annotated[dict[str, str], merge_dicts]

    # Final answer surfaced to the user (identical to the single agent
    # response until the synthesis agent does real multi-topic merging).
    final_answer: str

    # Execution trace: list of {"node", "action", "output", "duration_ms"}
    # dicts, used by evaluation/routing_metrics.py and the dashboard.
    execution_log: Annotated[list[dict], operator.add]


def initial_state(question: str) -> dict:
    """Base state dict for a fresh `graph.invoke()` call. Every
    reducer-backed field (the `Annotated[..., merge_dicts/operator.add]`
    ones above) needs an explicit empty value up front - LangGraph applies
    the reducer to combine a channel's current value with each update, so
    a channel that was never initialized has nothing to combine against.
    Centralizing this here means callers don't need to repeat every
    reducer field whenever a new one is added."""
    return {
        "question": question,
        "agent_responses": {},
        "subtopic_decisions": {},
        "selected_subtopics": {},
        "chapter_decisions": {},
        "selected_chapters": {},
        "retrieved_passages": {},
        "execution_log": [],
    }


def get_topic_question(state: RoutingState, topic: str) -> str:
    """The question text a per-topic classifier/agent should actually use
    for `topic`: the full original question for a single-topic question
    (byte-identical to Levels 1-6, zero risk of behavior change there),
    or the Topic Router's own per-topic restatement
    (`topic_decision.topic_questions[topic]`) for a multi-topic question
    (Level 7+).

    Used by `subtopic_router`, `chapter_selector`, `rag_retriever`, and
    every topic agent - direct testing showed that handing any of these a
    multi-topic question's *other* topic's fragment (even unintentionally,
    via the shared full `state["question"]`) could bleed into its
    decision: `subtopic_router` once misrouted a customer_support
    question's subtopic to 'delivery' instead of 'orders' purely because
    an unrelated washing-machine fragment was still present in the text
    it classified. Restating the question per topic removes that
    fragment entirely, which is more robust than instructing a
    classifier/agent to ignore text it can still see."""
    selected_topics = state.get("selected_topics", [])
    if len(selected_topics) <= 1:
        return state["question"]
    return state.get("topic_decision", {}).get("topic_questions", {}).get(topic, state["question"])
