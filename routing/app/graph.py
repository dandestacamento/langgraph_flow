"""Builds the LangGraph `StateGraph` for the Routing Accuracy Lab.

Current (Level 1) graph shape:

    START -> complexity_router -> topic_router -> {one agent per selected
    topic, via Send fan-out} -> synthesis_agent -> END

Level 1 only ever selects a single topic, so exactly one agent node runs
per question - but using `Send` for the fan-out (rather than a single
conditional edge) means Level 7 (multi-topic parallel routing) can select
more than one topic later without changing this wiring, only the topic
router's output.

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
from app.routers.complexity_router import classify_complexity
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
    """Conditional edge from topic_router: fan out to one Send per
    selected topic. A single-topic question (Level 1-6) produces exactly
    one Send; a multi-topic question (Level 7+) produces several, which
    LangGraph executes in parallel."""
    return [Send(_TOPIC_AGENT_NODES[topic], state) for topic in state["selected_topics"]]


def build_graph():
    graph = StateGraph(RoutingState)

    graph.add_node("complexity_router", classify_complexity)
    graph.add_node("topic_router", classify_topic)
    for topic, node_name in _TOPIC_AGENT_NODES.items():
        graph.add_node(node_name, _TOPIC_AGENT_FUNCS[topic])
    graph.add_node("synthesis_agent", synthesize)

    graph.add_edge(START, "complexity_router")
    graph.add_edge("complexity_router", "topic_router")
    graph.add_conditional_edges("topic_router", route_to_agents, list(_TOPIC_AGENT_NODES.values()))
    for node_name in _TOPIC_AGENT_NODES.values():
        graph.add_edge(node_name, "synthesis_agent")
    graph.add_edge("synthesis_agent", END)

    return graph.compile()
