"""Builds the LangGraph `StateGraph` for the Routing Accuracy Lab.

Current (Level 4) graph shape:

    START -> complexity_router -> topic_router -> subtopic_router ->
    chapter_selector -> rag_retriever -> {one agent per selected topic,
    via Send fan-out} -> synthesis_agent -> END

Level 1 only ever selects a single topic, so exactly one agent node runs
per question - but using `Send` for the fan-out (rather than a single
conditional edge) means Level 7 (multi-topic parallel routing) can select
more than one topic later without changing this wiring, only the topic
router's output.

`subtopic_router` (Level 2) classifies each selected topic's question into
one of that topic's subtopics. `chapter_selector` (Level 3) then narrows
that (topic, subtopic) pair down to a specific chapter_id, using the real
chapter metadata parsed from `knowledge_base/` - used for evaluation and
the dashboard, not for retrieval scoping. `rag_retriever` (Level 4)
retrieves the actual passages each topic agent is grounded in - topic
agents no longer answer from their own general knowledge; they answer
only from retrieved passages, or report insufficient information.

`complexity_decision` is recorded but doesn't yet change the path taken;
the branch it will drive (RAG for intermediate, multi-agent planning for
complex) is added in later levels once those scenarios exist to test it.
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
from app.agents.synthesis_agent import synthesize
from app.rag.retrieval import retrieve_evidence
from app.routers.chapter_selector import select_chapter
from app.routers.complexity_router import classify_complexity
from app.routers.subtopic_router import classify_subtopic
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
    """Conditional edge from rag_retriever: fan out to one Send per
    selected topic. A single-topic question (Level 1-6) produces exactly
    one Send; a multi-topic question (Level 7+) produces several, which
    LangGraph executes in parallel."""
    return [Send(_TOPIC_AGENT_NODES[topic], state) for topic in state["selected_topics"]]


def build_graph():
    graph = StateGraph(RoutingState)

    graph.add_node("complexity_router", classify_complexity)
    graph.add_node("topic_router", classify_topic)
    graph.add_node("subtopic_router", classify_subtopic)
    graph.add_node("chapter_selector", select_chapter)
    graph.add_node("rag_retriever", retrieve_evidence)
    for topic, node_name in _TOPIC_AGENT_NODES.items():
        graph.add_node(node_name, _TOPIC_AGENT_FUNCS[topic])
    graph.add_node("synthesis_agent", synthesize)

    graph.add_edge(START, "complexity_router")
    graph.add_edge("complexity_router", "topic_router")
    graph.add_edge("topic_router", "subtopic_router")
    graph.add_edge("subtopic_router", "chapter_selector")
    graph.add_edge("chapter_selector", "rag_retriever")
    graph.add_conditional_edges("rag_retriever", route_to_agents, list(_TOPIC_AGENT_NODES.values()))
    for node_name in _TOPIC_AGENT_NODES.values():
        graph.add_edge(node_name, "synthesis_agent")
    graph.add_edge("synthesis_agent", END)

    return graph.compile()
