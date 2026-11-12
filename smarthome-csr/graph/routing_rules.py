"""Conditional routing logic: decides which agent node(s) to run next based
on the router's classification.

Returning a list lets LangGraph fan out to multiple agents in parallel; for
the Phase 1 "basic routing" demos this will usually be a list with a single
entry, but the mechanism already supports Phase 3's multi-agent scenarios
(e.g. a fault that is also a warranty claim) without any graph changes.
"""

from __future__ import annotations

from graph.state import CSRState

# Only these agents are wired into the graph in Phase 1. `orders` and
# `returns` are added in later phases (see agents/orders_agent.py and
# agents/returns_agent.py).
IMPLEMENTED_AGENTS = {"product", "technical", "warranty"}


def route_to_agents(state: CSRState) -> list[str]:
    """Conditional edge function used after the router node."""
    selected = [agent for agent in state["selected_agents"] if agent in IMPLEMENTED_AGENTS]
    if not selected:
        # Fallback: no implemented agent confidently matched - send to the
        # product agent as a safe default rather than ending with no reply.
        selected = ["product"]
    return selected
