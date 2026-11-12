"""Orders Agent (placeholder, not yet wired into the graph).

Phase 2 ("Tools and state") will connect this to `tools.order_tools` to
answer delivery-status questions such as "Where is my delivery?" (use case 5
in instructions/SmartHome_Appliances/1_to_3_smarthome.md).
"""

from __future__ import annotations

from graph.state import CSRState


def orders_agent(state: CSRState) -> dict:
    raise NotImplementedError("orders_agent will be implemented in Phase 2.")
