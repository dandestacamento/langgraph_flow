"""Streamlit CSR dashboard for the SmartHome Appliances Assistant.

Run with: streamlit run app.py
"""

from __future__ import annotations

import uuid

import streamlit as st
from dotenv import load_dotenv
from langgraph.checkpoint.memory import InMemorySaver

from graph.workflow import build_graph

load_dotenv()

st.set_page_config(page_title="SmartHome Appliances - CSR Dashboard", layout="wide")


@st.cache_resource
def get_graph():
    # InMemorySaver persists conversation state (order_id, troubleshooting
    # history, ...) for the lifetime of this process, keyed by thread_id -
    # see graph/workflow.py's `extract_context` and `conversation_history`.
    return build_graph(checkpointer=InMemorySaver())


st.title("SmartHome Appliances — CSR Dashboard")
st.caption("Mock customer support application, built on LangGraph")

if "history" not in st.session_state:
    st.session_state.history = []
if "thread_id" not in st.session_state:
    # One thread_id per browser session = one persisted conversation.
    st.session_state.thread_id = str(uuid.uuid4())

chat_col, inspector_col = st.columns([2, 1])

with chat_col:
    st.subheader("Customer conversation")
    message = st.chat_input("Type the customer's message...")

    if message:
        graph = get_graph()
        config = {"configurable": {"thread_id": st.session_state.thread_id}}
        result = graph.invoke({"customer_message": message}, config=config)
        st.session_state.history.append((message, result))

    for customer_message, result in st.session_state.history:
        with st.chat_message("user"):
            st.write(customer_message)
        with st.chat_message("assistant"):
            st.write(result["final_response"])


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
