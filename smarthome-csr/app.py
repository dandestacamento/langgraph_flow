"""Streamlit CSR dashboard for the SmartHome Appliances Assistant.

Run with: streamlit run app.py
"""

from __future__ import annotations

import uuid

import streamlit as st
from dotenv import load_dotenv
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from graph.workflow import build_graph

load_dotenv()

st.set_page_config(page_title="SmartHome Appliances - CSR Dashboard", layout="wide")


@st.cache_resource
def get_graph():
    # InMemorySaver persists conversation state (order_id, troubleshooting
    # history, pending approvals, ...) for the lifetime of this process,
    # keyed by thread_id - see graph/workflow.py.
    return build_graph(checkpointer=InMemorySaver())


st.title("SmartHome Appliances — CSR Dashboard")
st.caption("Mock customer support application, built on LangGraph")

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


with inspector_col:
    st.subheader("Graph Execution Inspector")
    if st.session_state.history:
        _, last_result = st.session_state.history[-1]
        decision = last_result.get("router_decision") or {}
        st.markdown(f"**Intent(s):** {', '.join(decision.get('intents', [])) or 'n/a'}")
        st.markdown(f"**Confidence:** {decision.get('confidence', 'n/a')}")
        st.markdown(f"**Reasoning:** {decision.get('reasoning', 'n/a')}")
        st.divider()
        for i, entry in enumerate(last_result.get("execution_log", []), start=1):
            st.markdown(f"**{i}. {entry['node']}** — {entry['action']}")
            st.json(entry, expanded=False)
    else:
        st.info("Send a message to see the execution trace.")

