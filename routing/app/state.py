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

Level 8 adds `tool_decisions`/`tool_results`: one tool decision (and its
executed result, if any) per selected topic, keyed by topic in
`tool_decisions`/`tool_results`, following the same per-topic-dict
pattern as every stage above. Most questions still need no tool at all
(`needs_tool=False`) - `tool_results` only has an entry for a topic when
`select_tools` (`app/routers/tool_router.py`) actually ran one.

Level 9 adds `is_multi_hop`/`hop_plan`/`hop_results` for genuine
multi-hop questions, where a second sub-question literally cannot be
formed until the first's answer is known (e.g. "which washing machine
model has the largest capacity, and what's its price?" - the price
lookup needs the model name hop 1 resolves). This is architecturally
different from Level 7's multi-topic parallelism (independent
sub-questions, run together via `Send`) - these hops are sequential and
dependent, so they're resolved one at a time by
`app.agents.multihop_agent.execute_multihop`, which recursively invokes
`app.graph.build_graph()` once per hop (reusing the entire existing
single-question pipeline - topic/subtopic/chapter/retrieval/tool/agent -
unchanged) rather than adding a second routing mechanism. A dedicated
`app.routers.multihop_router.classify_multihop` node runs right after
`complexity_router` and conditionally routes to this path only when
`is_multi_hop` is true; every other question's existing pipeline
(`topic_router` onward) is completely untouched by Level 9.
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
ToolName = Literal["calculator", "sql_query", "metadata_lookup"]


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


class ToolDecision(TypedDict):
    needs_tool: bool
    tool_name: ToolName | None
    tool_input: str | None
    reasoning: str


class ToolResult(TypedDict):
    tool_name: ToolName
    tool_input: str
    output: str | None
    error: str | None


class HopPlan(TypedDict):
    """Level 9: the (at most two-hop) decomposition of a multi-hop
    question. `hop2_question_template` contains the literal placeholder
    text `{hop1_answer}`, substituted with hop 1's extracted value before
    hop 2 is resolved - see `app.agents.multihop_agent` for why a plain
    string template (rather than a structured query object) is enough:
    every Level 9 hop 2 is itself just an ordinary single-topic question
    once the placeholder is filled in, answerable by the existing
    pipeline with no further special-casing."""

    hop1_question: str
    hop2_question_template: str
    reasoning: str


class HopResult(TypedDict):
    """One resolved hop: the question actually asked (after substitution,
    for hop 2), the full final_answer the existing pipeline produced for
    it, and (if this isn't the last hop) the specific short value
    extracted from that answer to substitute into the next hop's
    template."""

    hop_number: int
    question: str
    final_answer: str
    extracted_value: str | None


class RoutingState(TypedDict):
    # Input
    question: str

    # Stage 1 (complexity_router): simple/intermediate/complex classification.
    complexity_decision: ComplexityDecision | None

    # Set True only on the sub-invocations `multihop_agent` makes for
    # hop 1/hop 2 - guards against unbounded recursion if a hop's own
    # question (e.g. after `{hop1_answer}` substitution) would otherwise
    # itself be classified as multi-hop by `multihop_router` and sent
    # back into `multihop_agent` again. When true, `multihop_router` is
    # skipped entirely (see `app.graph.route_after_complexity`) - a hop
    # is always treated as an ordinary single-pass question, by design
    # (every Level 9 hop 2 is just an ordinary question once its
    # placeholder is filled in; see `HopPlan`'s docstring).
    is_hop_subquestion: bool

    # Stage 1b (multihop_router, Level 9): is this a genuine multi-hop
    # question, and if so, its (at most two-hop) decomposition plan.
    is_multi_hop: bool
    hop_plan: HopPlan | None
    hop_results: Annotated[list[HopResult], operator.add]

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

    # Stage 3b (tool_router): one tool decision (and, if a tool actually
    # ran, its result) per selected topic.
    tool_decisions: Annotated[dict[str, ToolDecision], merge_dicts]
    tool_results: Annotated[dict[str, ToolResult], merge_dicts]

    # One entry per topic agent that ran, merged via reducer so multiple
    # agents can run in parallel (Level 7+) without overwriting each other.
    agent_responses: Annotated[dict[str, str], merge_dicts]

    # Final answer surfaced to the user (identical to the single agent
    # response until the synthesis agent does real multi-topic merging).
    final_answer: str

    # Execution trace: list of {"node", "action", "output", "duration_ms"}
    # dicts, used by evaluation/routing_metrics.py and the dashboard.
    execution_log: Annotated[list[dict], operator.add]


def initial_state(question: str, is_hop_subquestion: bool = False) -> dict:
    """Base state dict for a fresh `graph.invoke()` call. Every
    reducer-backed field (the `Annotated[..., merge_dicts/operator.add]`
    ones above) needs an explicit empty value up front - LangGraph applies
    the reducer to combine a channel's current value with each update, so
    a channel that was never initialized has nothing to combine against.
    Centralizing this here means callers don't need to repeat every
    reducer field whenever a new one is added.

    `is_hop_subquestion` is set True only by `app.agents.multihop_agent`
    when invoking the graph for one of its own hops - see
    `RoutingState.is_hop_subquestion`'s docstring for why that's needed
    (prevents unbounded multi-hop-within-multi-hop recursion)."""
    return {
        "question": question,
        "is_hop_subquestion": is_hop_subquestion,
        "agent_responses": {},
        "subtopic_decisions": {},
        "selected_subtopics": {},
        "chapter_decisions": {},
        "selected_chapters": {},
        "retrieved_passages": {},
        "tool_decisions": {},
        "tool_results": {},
        "hop_results": [],
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
