"""Graph visualization helper: renders the compiled LangGraph workflow as
Mermaid, for the README, the Streamlit dashboard, and quick debugging of
the conditional edges actually wired up at each level.
"""

from __future__ import annotations

from typing import Any


def render_graph_diagram(compiled_graph: Any) -> tuple[bytes | None, str]:
    """Render a compiled LangGraph graph as a PNG (via Mermaid's remote
    render service) alongside the raw Mermaid source. Falls back to
    `(None, mermaid_source)` if the render service can't be reached, so
    callers can always show something (e.g. `st.code` of the source)."""
    graph = compiled_graph.get_graph()
    mermaid_source = graph.draw_mermaid()
    try:
        png_bytes = graph.draw_mermaid_png()
    except Exception:
        return None, mermaid_source
    return png_bytes, mermaid_source
