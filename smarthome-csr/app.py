"""Streamlit CSR dashboard for the SmartHome Appliances Assistant.

Run with: streamlit run app.py
"""

from __future__ import annotations

import streamlit as st
from dotenv import load_dotenv

from graph.workflow import build_graph

load_dotenv()

st.set_page_config(page_title="SmartHome Appliances - CSR Dashboard", layout="wide")


@st.cache_resource
def get_graph():
    return build_graph()


def new_state(message: str) -> dict:
    return {
        "customer_message": message,
        "order_id": None,
        "router_decision": None,
        "selected_agents": [],
        "agent_responses": {},
        "final_response": "",
        "execution_log": [],
    }


st.title("SmartHome Appliances — CSR Dashboard")
st.caption("Mock customer support application, built on LangGraph")

if "history" not in st.session_state:
    st.session_state.history = []

chat_col, inspector_col = st.columns([2, 1])

with chat_col:
    st.subheader("Customer conversation")
    message = st.chat_input("Type the customer's message...")

    if message:
        graph = get_graph()
        result = graph.invoke(new_state(message))
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
