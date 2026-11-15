"""Builds the LangGraph `StateGraph` for the Routing Accuracy Lab.

Current (Level 9) graph shape:

    START -> complexity_router -> multihop_router -> {conditional}
      - if is_multi_hop: -> multihop_agent -> END
      - else: -> topic_router -> {conditional}
        - if is_ambiguous: -> clarification_agent -> END
        - else: -> subtopic_router -> chapter_selector -> rag_retriever ->
          tool_router -> {one agent per selected topic, via Send fan-out} ->
          synthesis_agent -> END

Levels 1-6 only ever select a single topic, so exactly one agent node runs
per question - but using `Send` for the fan-out (rather than a single
conditional edge) meant Level 7 (multi-topic parallel routing) could
select more than one topic without changing this wiring at all, only the
topic router's output and the synthesis agent's merge logic.

`subtopic_router` (Level 2) classifies each selected topic's question into
one of that topic's subtopics. `chapter_selector` (Level 3) then narrows
that (topic, subtopic) pair down to a specific chapter_id - used for
evaluation and the dashboard, not for retrieval scoping (see
`app/rag/retrieval.py` for why retrieval is scoped to subtopic, not the
single chapter guess). `rag_retriever` (Level 4) retrieves the actual
passages each topic agent is grounded in - topic agents no longer answer
from their own general knowledge; they answer only from retrieved
passages, or report insufficient information.

`topic_router` (Level 5) now also flags `is_ambiguous` - when true, the
graph skips the entire subtopic/chapter/retrieval/answer pipeline and
routes straight to `clarification_agent`, which asks the user a clarifying
question instead of guessing. This catches ambiguity *before* spending a
retrieval+generation call on a question that would otherwise be answered
plausibly but wrongly - Level 4's insufficient-information handling can't
catch this case, since the retrieved passages for a wrong-but-plausible
topic guess aren't obviously irrelevant. `clarification_agent` routes
directly to END, bypassing `synthesis_agent` (which would otherwise
overwrite `final_answer` with an empty string, since no topic agent ran).

`synthesis_agent` (Level 7) now does real multi-topic merging: when
`topic_router` selects more than one topic, every selected topic's agent
runs in parallel via `route_to_agents`' `Send` fan-out, and
`synthesis_agent` makes one extra LLM call to merge their already-grounded,
already-cited answers into a single coherent response - for the
single-topic case (still the overwhelming majority of questions) it
remains a free pass-through with no extra call, so Level 7 adds cost only
for genuinely multi-topic questions.

`tool_router` (Level 8) decides, per selected topic, whether answering
needs `calculator`, `sql_query`, or `metadata_lookup` beyond what
`rag_retriever` already found - and if so, executes it immediately so the
topic agent can incorporate the result. Placed after `rag_retriever` since
it needs `selected_subtopics` (for the `sql_query` schema) but not the
retrieved passages themselves; most questions still need no tool at all,
so this adds cost only when a tool is genuinely selected.

`multihop_router` (Level 9) runs right after `complexity_router` and
decides whether the question is genuinely multi-hop - a second part whose
subject isn't named yet, only a reference to whatever a first part
identifies (see that module's docstring for why this is a different
thing from Levels 6/7/8's compound questions). When true, `multihop_agent`
takes over entirely: it resolves hop 1 and hop 2 by recursively invoking
this very `build_graph()` on each hop's own self-contained question text
(reusing the whole existing single-question pipeline unchanged for each
hop), then synthesizes the final answer - bypassing `topic_router`
onward completely for that question, the same way `clarification_agent`
bypasses the rest of the pipeline for an ambiguous one. For every
non-multi-hop question (still the overwhelming majority), this adds
exactly one extra classification call and otherwise doesn't touch
anything - `topic_router` onward is completely unchanged from Level 8.
`multihop_router` is itself skipped entirely for `multihop_agent`'s own
hop sub-invocations (`is_hop_subquestion=True`) - without this guard, a
hop's own question could in principle also look multi-hop and recurse
into `multihop_agent` again unboundedly.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.agents import (
    appliance_agent,
    azure_agent,
    customer_support_agent,
    data_engineering_agent,
    finance_agent,
    python_agent,
)
from app.agents.clarification_agent import ask_for_clarification
from app.agents.multihop_agent import execute_multihop
from app.agents.synthesis_agent import synthesize
from app.rag.retrieval import retrieve_evidence
from app.routers.chapter_selector import select_chapter
from app.routers.complexity_router import classify_complexity
from app.routers.multihop_router import classify_multihop
from app.routers.subtopic_router import classify_subtopic
from app.routers.tool_router import select_tools
from app.routers.topic_router import classify_topic
from app.state import RoutingState

_TOPIC_AGENT_NODES = {
    "appliances": "appliances_agent",
    "azure_cloud": "azure_cloud_agent",
    "data_engineering": "data_engineering_agent",
    "python": "python_agent",
    "finance": "finance_agent",
    "customer_support": "customer_support_agent",
}

_TOPIC_AGENT_FUNCS = {
    "appliances": appliance_agent.run,
    "azure_cloud": azure_agent.run,
    "data_engineering": data_engineering_agent.run,
    "python": python_agent.run,
    "finance": finance_agent.run,
    "customer_support": customer_support_agent.run,
}


def route_to_agents(state: RoutingState) -> list[Send]:
    """Conditional edge from tool_router: fan out to one Send per
    selected topic. A single-topic question (the common case through
    Level 6) produces exactly one Send; a multi-topic question (Level 7)
    produces several, which LangGraph executes in parallel."""
    return [Send(_TOPIC_AGENT_NODES[topic], state) for topic in state["selected_topics"]]


def route_after_topic(state: RoutingState) -> str:
    """Conditional edge from topic_router: skip straight to the
    clarification agent (bypassing subtopic/chapter/retrieval entirely)
    when the question was flagged as ambiguous."""
    if state["topic_decision"]["is_ambiguous"]:
        return "clarification_agent"
    return "subtopic_router"


def route_after_complexity(state: RoutingState) -> str:
    """Conditional edge from complexity_router: skip `multihop_router`
    entirely for a hop sub-question (`is_hop_subquestion=True`, set only
    by `multihop_agent`'s own recursive invocations) - a hop is always
    treated as an ordinary single-pass question by design, both to avoid
    unbounded multi-hop-within-multi-hop recursion if a hop's own
    question would otherwise also look multi-hop, and to save a
    classification call that would always need to answer false anyway."""
    if state.get("is_hop_subquestion", False):
        return "topic_router"
    return "multihop_router"


def route_after_multihop(state: RoutingState) -> str:
    """Conditional edge from multihop_router: skip the entire normal
    pipeline (topic/subtopic/chapter/retrieval/tool/agent/synthesis) and
    go straight to `multihop_agent` when the question was flagged as
    genuinely multi-hop."""
    if state["is_multi_hop"]:
        return "multihop_agent"
    return "topic_router"


def build_graph():
    graph = StateGraph(RoutingState)

    graph.add_node("complexity_router", classify_complexity)
    graph.add_node("multihop_router", classify_multihop)
    graph.add_node("multihop_agent", execute_multihop)
    graph.add_node("topic_router", classify_topic)
    graph.add_node("clarification_agent", ask_for_clarification)
    graph.add_node("subtopic_router", classify_subtopic)
    graph.add_node("chapter_selector", select_chapter)
    graph.add_node("rag_retriever", retrieve_evidence)
    graph.add_node("tool_router", select_tools)
    for topic, node_name in _TOPIC_AGENT_NODES.items():
        graph.add_node(node_name, _TOPIC_AGENT_FUNCS[topic])
    graph.add_node("synthesis_agent", synthesize)

    graph.add_edge(START, "complexity_router")
    graph.add_conditional_edges(
        "complexity_router", route_after_complexity, ["multihop_router", "topic_router"]
    )
    graph.add_conditional_edges(
        "multihop_router", route_after_multihop, ["multihop_agent", "topic_router"]
    )
    graph.add_edge("multihop_agent", END)
    graph.add_conditional_edges(
        "topic_router", route_after_topic, ["clarification_agent", "subtopic_router"]
    )
    graph.add_edge("clarification_agent", END)
    graph.add_edge("subtopic_router", "chapter_selector")
    graph.add_edge("chapter_selector", "rag_retriever")
    graph.add_edge("rag_retriever", "tool_router")
    graph.add_conditional_edges("tool_router", route_to_agents, list(_TOPIC_AGENT_NODES.values()))
    for node_name in _TOPIC_AGENT_NODES.values():
        graph.add_edge(node_name, "synthesis_agent")
    graph.add_edge("synthesis_agent", END)

    return graph.compile()
