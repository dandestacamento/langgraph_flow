"""Returns Agent (placeholder, not yet wired into the graph).

Phase 3 ("Advanced orchestration") will connect this to a refund-policy
evaluator and the human-in-the-loop Approval Gate, since refund requests
often require CSR supervisor sign-off (see data/policies.json).
"""

from __future__ import annotations

from graph.state import CSRState


def returns_agent(state: CSRState) -> dict:
    raise NotImplementedError("returns_agent will be implemented in Phase 3.")
