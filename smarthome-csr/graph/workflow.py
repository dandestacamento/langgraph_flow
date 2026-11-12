"""LangGraph StateGraph wiring for the SmartHome Appliances CSR Assistant.

Phase 3 graph:

    START -> extract_context -> router -> (product | technical | warranty
          | orders | returns) -> aggregator -> END

    returns -> approval_gate -> aggregator   (only when pending_approval is set)

`route_to_agents` can return more than one agent name, in which case
LangGraph runs the matching nodes in parallel and merges their results into
`agent_responses` via the reducer declared in `graph.state.CSRState`.

Phase 2 conversation memory: pass a `checkpointer` (e.g.
`langgraph.checkpoint.memory.InMemorySaver`) to persist state between
separate `.invoke()` calls that share the same `thread_id`. Fields like
`order_id` are only overwritten when a node explicitly returns that key, so
a value learned on an earlier turn (e.g. an order number) survives into
later turns without the customer repeating it (use case 8).

Phase 3 human-in-the-loop approval: when the Returns Agent sets
`pending_approval` (see agents/returns_agent.py), the graph routes to
`approval_gate` instead of straight to the aggregator. `approval_gate` calls
LangGraph's `interrupt()`, which pauses the graph and returns control to the
caller with an `"__interrupt__"` key in the result - this requires a
checkpointer, since LangGraph needs somewhere to persist the paused state.
The caller resumes the same `thread_id` with
`graph.invoke(Command(resume=<"approve" or "deny">), config=config)`.
"""

from __future__ import annotations

import time

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agents.orders_agent import orders_agent
from agents.product_agent import product_agent
from agents.returns_agent import returns_agent
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
    "returns": returns_agent,
}

APPROVED_RESPONSES = {"approve", "approved", "yes", "y", "true"}


def extract_context(state: CSRState) -> dict:
    """Pull sticky conversation context (currently: an order number) out of
    the latest message. Only returns `order_id` when one is actually found,
    so a value learned on an earlier turn is never overwritten with None."""
    order_id = extract_order_id(state["customer_message"])
    if order_id is None:
        return {}
    return {"order_id": order_id}


def approval_gate(state: CSRState) -> dict:
    """Pause the graph for CSR sign-off on a pending Returns Agent request.

    Any code here before `interrupt()` re-runs on resume (LangGraph re-enters
    the node from the top), so it must stay side-effect free.
    """
    start = time.perf_counter()
    pending = state["pending_approval"]

    decision = interrupt(
        {
            "type": "approval_request",
            "agent": pending["agent"],
            "order_id": pending["order_id"],
            "amount": pending["amount"],
            "reason": pending["reason"],
            "prompt": (
                f"CSR approval needed: {pending['reason']} "
                f"(${pending['amount']:.2f} AUD). Approve or deny?"
            ),
        }
    )
    approved = str(decision).strip().lower() in APPROVED_RESPONSES
    duration_ms = (time.perf_counter() - start) * 1000

    agent_name = pending["agent"]
    existing_response = state.get("agent_responses", {}).get(agent_name, "")
    addendum = (
        "\n\nSupervisor approval granted - we will proceed with the refund/replacement."
        if approved
        else "\n\nThis could not be approved automatically; a supervisor will follow up with you."
    )

    return {
        "agent_responses": {agent_name: existing_response + addendum},
        "pending_approval": None,
        "approval_decision": "approved" if approved else "denied",
        "execution_log": [
            {
                "node": "approval_gate",
                "action": "human_approval",
                "decision": "approved" if approved else "denied",
                "pending_approval": pending,
                "duration_ms": round(duration_ms, 1),
            }
        ],
    }


def _needs_approval(state: CSRState) -> str:
    """Conditional edge used after the Returns agent."""
    return "approval_gate" if state.get("pending_approval") else "aggregator"


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
    (required for sticky `order_id`, the Technical agent's troubleshooting
    escalation, and the Approval Gate's `interrupt()`/resume); omit it for
    stateless, single-shot invocations like most unit/integration tests use.
    """
    graph = StateGraph(CSRState)

    graph.add_node("extract_context", extract_context)
    graph.add_node("router", classify_intent)
    for name, node_fn in AGENT_NODES.items():
        graph.add_node(name, node_fn)
    graph.add_node("approval_gate", approval_gate)
    graph.add_node("aggregator", aggregate_responses)

    graph.add_edge(START, "extract_context")
    graph.add_edge("extract_context", "router")
    graph.add_conditional_edges("router", route_to_agents, list(IMPLEMENTED_AGENTS))
    for name in AGENT_NODES:
        if name == "returns":
            graph.add_conditional_edges(name, _needs_approval, ["approval_gate", "aggregator"])
        else:
            graph.add_edge(name, "aggregator")
    graph.add_edge("approval_gate", "aggregator")
    graph.add_edge("aggregator", END)

    return graph.compile(checkpointer=checkpointer)
