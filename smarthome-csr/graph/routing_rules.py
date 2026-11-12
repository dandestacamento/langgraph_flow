"""Conditional routing logic: decides which agent node(s) to run next based
on the router's classification.

Returning a list lets LangGraph fan out to multiple agents in parallel; for
example a fault that's also a warranty claim routes to both `technical` and
`warranty` at once, which `graph.workflow` merges via the `agent_responses`
reducer and the aggregator node.
"""

from __future__ import annotations

from graph.state import CSRState

# All five specialist agents are wired into the graph as of Phase 3. This
# set is kept as a defensive filter against any agent name the router might
# hallucinate that isn't an actual graph node.
IMPLEMENTED_AGENTS = {"product", "technical", "warranty", "orders", "returns"}


def route_to_agents(state: CSRState) -> list[str]:
    """Conditional edge function used after the router node."""
    selected = [agent for agent in state["selected_agents"] if agent in IMPLEMENTED_AGENTS]
    if not selected:
        # Fallback: no implemented agent confidently matched - send to the
        # product agent as a safe default rather than ending with no reply.
        selected = ["product"]
    return selected
