"""LangGraph StateGraph wiring for the SmartHome Appliances CSR Assistant.

Phase 2 graph:

    START -> extract_context -> router -> (product | technical | warranty | orders)
          -> aggregator -> END

`route_to_agents` can return more than one agent name, in which case
LangGraph runs the matching nodes in parallel and merges their results into
`agent_responses` via the reducer declared in `graph.state.CSRState`. That
lets this same graph scale to Phase 3's multi-agent scenarios without
structural changes - only `routing_rules.IMPLEMENTED_AGENTS` and
`AGENT_NODES` below need to grow.

Phase 2 conversation memory: pass a `checkpointer` (e.g.
`langgraph.checkpoint.memory.InMemorySaver`) to persist state between
separate `.invoke()` calls that share the same `thread_id`. Fields like
`order_id` are only overwritten when a node explicitly returns that key, so
a value learned on an earlier turn (e.g. an order number) survives into
later turns without the customer repeating it (use case 8).
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from agents.orders_agent import orders_agent
from agents.product_agent import product_agent
from agents.technical_agent import technical_agent
from agents.warranty_agent import warranty_agent
from graph.router import classify_intent
from graph.routing_rules import IMPLEMENTED_AGENTS, route_to_agents
from graph.state import CSRState
from tools.order_tools import extract_order_id

AGENT_NODES = {
    "product": product_agent,
    "technical": technical_agent,
    "warranty": warranty_agent,
    "orders": orders_agent,
}


def extract_context(state: CSRState) -> dict:
    """Pull sticky conversation context (currently: an order number) out of
    the latest message. Only returns `order_id` when one is actually found,
    so a value learned on an earlier turn is never overwritten with None."""
    order_id = extract_order_id(state["customer_message"])
    if order_id is None:
        return {}
    return {"order_id": order_id}


def aggregate_responses(state: CSRState) -> dict:
    """Combine every agent's response into the single reply shown to the CSR,
    and record this turn in `conversation_history` for later turns (e.g. the
    Technical agent's repeat-visit escalation)."""
    responses = state.get("agent_responses", {})
    selected_agents = state["selected_agents"]
    ordered = [responses[name] for name in selected_agents if name in responses]
    final_response = "\n\n".join(ordered) if ordered else "I wasn't able to find an answer to that."

    return {
        "final_response": final_response,
        "conversation_history": [
            {
                "customer_message": state["customer_message"],
                "agents": selected_agents,
                "response": final_response,
            }
        ],
        "execution_log": [
            {
                "node": "aggregator",
                "action": "aggregate_responses",
                "output": {"agents_combined": list(responses.keys())},
            }
        ],
    }


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    """Compile the SmartHome CSR LangGraph workflow.

    Pass a `checkpointer` to enable conversation persistence across turns
    (required for sticky `order_id` and the Technical agent's troubleshooting
    escalation); omit it for stateless, single-shot invocations like the
    unit/integration tests use.
    """
    graph = StateGraph(CSRState)

    graph.add_node("extract_context", extract_context)
    graph.add_node("router", classify_intent)
    for name, node_fn in AGENT_NODES.items():
        graph.add_node(name, node_fn)
    graph.add_node("aggregator", aggregate_responses)

    graph.add_edge(START, "extract_context")
    graph.add_edge("extract_context", "router")
    graph.add_conditional_edges("router", route_to_agents, list(IMPLEMENTED_AGENTS))
    for name in AGENT_NODES:
        graph.add_edge(name, "aggregator")
    graph.add_edge("aggregator", END)

    return graph.compile(checkpointer=checkpointer)
