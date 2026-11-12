"""Conditional routing logic: decides which agent node(s) to run next based
on the router's classification.

Returning a list lets LangGraph fan out to multiple agents in parallel; for
the Phase 1 "basic routing" demos this will usually be a list with a single
entry, but the mechanism already supports Phase 3's multi-agent scenarios
(e.g. a fault that is also a warranty claim) without any graph changes.
"""

from __future__ import annotations

from graph.state import CSRState

# Agents wired into the graph so far (Phase 1: product/technical/warranty,
# Phase 2 adds orders). `returns` is added in Phase 3, alongside the human
# approval gate it needs (see agents/returns_agent.py).
IMPLEMENTED_AGENTS = {"product", "technical", "warranty", "orders"}


def route_to_agents(state: CSRState) -> list[str]:
    """Conditional edge function used after the router node."""
    selected = [agent for agent in state["selected_agents"] if agent in IMPLEMENTED_AGENTS]
    if not selected:
        # Fallback: no implemented agent confidently matched - send to the
        # product agent as a safe default rather than ending with no reply.
        selected = ["product"]
    return selected
