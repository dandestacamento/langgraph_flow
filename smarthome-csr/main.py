"""Application entry point for the SmartHome Appliances CSR Assistant.

Run this directly for a quick command-line smoke test of the LangGraph
workflow before launching the Streamlit dashboard (`streamlit run app.py`).
"""

from __future__ import annotations

import os

import mlflow
from dotenv import load_dotenv
from langgraph.checkpoint.memory import InMemorySaver

from graph.workflow import build_graph

SAMPLE_MESSAGES = [
    "Do you have a Bosch Series 6 dishwasher in stock?",
    "My washing machine makes a loud banging noise during spinning.",
    "Is my refrigerator still under warranty? Order ORD-1045.",
]

# A two-turn conversation on the SAME thread_id, demonstrating Phase 2
# conversation memory: the order number given on turn 1 is still known on
# turn 2 without being repeated, and the Technical agent escalates instead
# of repeating the same troubleshooting steps (use cases 3 and 8).
FOLLOW_UP_CONVERSATION = [
    "My washing machine (order ORD-1045) is making a loud banging noise during spinning.",
    "I tried that already and it's still banging. What now?",
]


def run_single_turn_demo(graph) -> None:
    for i, message in enumerate(SAMPLE_MESSAGES):
        config = {"configurable": {"thread_id": f"single-turn-{i}"}}
        result = graph.invoke({"customer_message": message}, config=config)
        print(f"\nCustomer: {message}")
        print(f"Router -> {result['router_decision']}")
        print(f"CSR reply:\n{result['final_response']}")


def run_follow_up_demo(graph) -> None:
    print("\n--- Conversation memory demo (same thread_id across turns) ---")
    config = {"configurable": {"thread_id": "demo-conversation-1"}}
    for message in FOLLOW_UP_CONVERSATION:
        result = graph.invoke({"customer_message": message}, config=config)
        print(f"\nCustomer: {message}")
        print(f"CSR reply:\n{result['final_response']}")


if __name__ == "__main__":
    load_dotenv()  # reads OPENAI_API_KEY (and others) from .env

    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000"))
    mlflow.set_experiment("smarthome_csr")
    mlflow.langchain.autolog()

    # InMemorySaver keeps conversation state for the lifetime of this
    # process, keyed by thread_id. Swap in a persistent checkpointer (e.g.
    # SqliteSaver) if state needs to survive a process restart.
    demo_graph = build_graph(checkpointer=InMemorySaver())
    run_single_turn_demo(demo_graph)
    run_follow_up_demo(demo_graph)

