"""Streamlit CSR dashboard for the SmartHome Appliances Assistant.

Run with: streamlit run app.py
"""

from __future__ import annotations

import os
import socket
import uuid
from urllib.parse import urlparse

import streamlit as st
from dotenv import load_dotenv
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from graph.workflow import build_graph

load_dotenv()

st.set_page_config(page_title="SmartHome Appliances - CSR Dashboard", layout="wide")


def _enable_mlflow_tracing_if_available(tracking_uri: str, experiment: str, timeout: float = 0.5) -> bool:
    """Enable MLflow autologging only if the tracking server is actually
    reachable. `mlflow.set_experiment()` blocks (effectively hangs the app)
    when the server is unreachable, and MLflow is meant to run on-demand
    here (see start_mlflow.ps1), not always-on - so this does a quick
    socket check first instead of letting the app freeze on startup."""
    parsed = urlparse(tracking_uri)
    host, port = parsed.hostname or "127.0.0.1", parsed.port or 80
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError:
        return False

    import mlflow

    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(experiment)
    mlflow.langchain.autolog()
    return True


@st.cache_resource
def get_graph():
    # InMemorySaver persists conversation state (order_id, troubleshooting
    # history, pending approvals, ...) for the lifetime of this process,
    # keyed by thread_id - see graph/workflow.py.
    return build_graph(checkpointer=InMemorySaver())


@st.cache_resource
def get_mlflow_status() -> bool:
    return _enable_mlflow_tracing_if_available(
        os.environ.get("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000"), "smarthome_csr"
    )


@st.cache_resource
def get_graph_diagram() -> tuple[bytes | None, str]:
    """Render the compiled graph as a PNG (via LangGraph's mermaid.ink
    integration) for display with st.image(). Falls back to the raw
    Mermaid source (pasteable into https://mermaid.live) if that render
    service isn't reachable, e.g. no internet access."""
    mermaid_source = build_graph().get_graph().draw_mermaid()
    try:
        png_bytes = build_graph().get_graph().draw_mermaid_png()
    except Exception:
        return None, mermaid_source
    return png_bytes, mermaid_source


st.title("SmartHome Appliances — CSR Dashboard")
title_col, status_col = st.columns([4, 1])
title_col.caption("Mock customer support application, built on LangGraph")
if get_mlflow_status():
    status_col.caption("🟢 MLflow tracing active")
else:
    status_col.caption("⚪ MLflow not running")

with st.expander("🗺️ Graph visualization"):
    png_bytes, mermaid_source = get_graph_diagram()
    if png_bytes:
        st.image(png_bytes, caption="SmartHome CSR LangGraph workflow")
    else:
        st.warning("Couldn't reach the Mermaid render service - showing diagram source instead.")
        st.code(mermaid_source, language="text")

if "history" not in st.session_state:
    st.session_state.history = []
if "thread_id" not in st.session_state:
    # One thread_id per browser session = one persisted conversation.
    st.session_state.thread_id = str(uuid.uuid4())
if "pending_interrupt" not in st.session_state:
    # Set while the graph is paused at the Approval Gate, waiting on a CSR
    # decision. Holds {"customer_message": ..., "request": <interrupt payload>}.
    st.session_state.pending_interrupt = None

config = {"configurable": {"thread_id": st.session_state.thread_id}}

chat_col, inspector_col = st.columns([2, 1])

with chat_col:
    st.subheader("Customer conversation")

    awaiting_approval = st.session_state.pending_interrupt is not None
    message = st.chat_input(
        "Awaiting CSR approval below..." if awaiting_approval else "Type the customer's message...",
        disabled=awaiting_approval,
    )

    if message and not awaiting_approval:
        graph = get_graph()
        result = graph.invoke({"customer_message": message}, config=config)
        if "__interrupt__" in result:
            st.session_state.pending_interrupt = {
                "customer_message": message,
                "request": result["__interrupt__"][0].value,
            }
            st.rerun()  # fresh rerun so chat_input/approval UI reflect the new state immediately
        else:
            st.session_state.history.append((message, result))

    for customer_message, result in st.session_state.history:
        with st.chat_message("user"):
            st.write(customer_message)
        with st.chat_message("assistant"):
            st.write(result["final_response"])

    if awaiting_approval:
        pending = st.session_state.pending_interrupt
        with st.chat_message("user"):
            st.write(pending["customer_message"])
        with st.chat_message("assistant"):
            st.warning(f"**Human approval required:** {pending['request']['prompt']}")
            approve_col, deny_col = st.columns(2)
            graph = get_graph()
            if approve_col.button("✅ Approve", use_container_width=True):
                result = graph.invoke(Command(resume="approve"), config=config)
                st.session_state.history.append((pending["customer_message"], result))
                st.session_state.pending_interrupt = None
                st.rerun()
            if deny_col.button("❌ Deny", use_container_width=True):
                result = graph.invoke(Command(resume="deny"), config=config)
                st.session_state.history.append((pending["customer_message"], result))
                st.session_state.pending_interrupt = None
                st.rerun()


def _group_log_by_turn(execution_log: list[dict]) -> list[list[dict]]:
    """Split the full (conversation-spanning) execution_log into per-turn
    groups, starting a new group at each 'router' entry. A turn paused by
    the Approval Gate spans two graph.invoke() calls (the initial one and
    the resume), but stays in one group here since `router` doesn't re-run
    on resume."""
    groups: list[list[dict]] = []
    for entry in execution_log:
        if entry["node"] == "router" or not groups:
            groups.append([])
        groups[-1].append(entry)
    return groups


with inspector_col:
    st.subheader("Graph Execution Inspector")
    if st.session_state.pending_interrupt:
        st.info("⏸️ Execution paused, awaiting CSR approval above.")
    if st.session_state.history:
        _, last_result = st.session_state.history[-1]
        turns = _group_log_by_turn(last_result.get("execution_log", []))

        turn_choice = st.selectbox(
            "Turn", options=list(range(len(turns), 0, -1)), format_func=lambda n: f"Turn {n}"
        )
        selected_log = turns[turn_choice - 1]

        decision = last_result.get("router_decision") or {}
        if turn_choice == len(turns):
            st.markdown(f"**Intent(s):** {', '.join(decision.get('intents', [])) or 'n/a'}")
            st.markdown(f"**Confidence:** {decision.get('confidence', 'n/a')}")
            st.markdown(f"**Reasoning:** {decision.get('reasoning', 'n/a')}")

        total_ms = sum(e.get("duration_ms", 0) for e in selected_log)
        st.caption(f"Total duration this turn: {total_ms:.1f} ms")
        st.divider()
        for i, entry in enumerate(selected_log, start=1):
            st.markdown(f"**{i}. {entry['node']}** — {entry['action']}")
            st.json(entry, expanded=False)
    else:
        st.info("Send a message to see the execution trace.")


