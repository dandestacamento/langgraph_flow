"""LangGraph StateGraph wiring for the SmartHome Appliances CSR Assistant.

Phase 1 graph:

    START -> router -> (product | technical | warranty) -> aggregator -> END

`route_to_agents` can return more than one agent name, in which case
LangGraph runs the matching nodes in parallel and merges their results into
`agent_responses` via the reducer declared in `graph.state.CSRState`. That
lets this same graph scale to Phase 3's multi-agent scenarios without
structural changes - only `routing_rules.IMPLEMENTED_AGENTS` and
`AGENT_NODES` below need to grow.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agents.product_agent import product_agent
from agents.technical_agent import technical_agent
from agents.warranty_agent import warranty_agent
from graph.router import classify_intent
from graph.routing_rules import IMPLEMENTED_AGENTS, route_to_agents
from graph.state import CSRState

AGENT_NODES = {
    "product": product_agent,
    "technical": technical_agent,
    "warranty": warranty_agent,
}


def aggregate_responses(state: CSRState) -> dict:
    """Combine every agent's response into the single reply shown to the CSR."""
    responses = state.get("agent_responses", {})
    ordered = [responses[name] for name in state["selected_agents"] if name in responses]
    final_response = "\n\n".join(ordered) if ordered else "I wasn't able to find an answer to that."

    return {
        "final_response": final_response,
        "execution_log": [
            {
                "node": "aggregator",
                "action": "aggregate_responses",
                "output": {"agents_combined": list(responses.keys())},
            }
        ],
    }


def build_graph():
    """Compile the Phase 1 SmartHome CSR LangGraph workflow."""
    graph = StateGraph(CSRState)

    graph.add_node("router", classify_intent)
    for name, node_fn in AGENT_NODES.items():
        graph.add_node(name, node_fn)
    graph.add_node("aggregator", aggregate_responses)

    graph.add_edge(START, "router")
    graph.add_conditional_edges("router", route_to_agents, list(IMPLEMENTED_AGENTS))
    for name in AGENT_NODES:
        graph.add_edge(name, "aggregator")
    graph.add_edge("aggregator", END)

    return graph.compile()
