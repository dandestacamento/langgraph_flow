"""Application entry point for the SmartHome Appliances CSR Assistant.

Run this directly for a quick command-line smoke test of the LangGraph
workflow before launching the Streamlit dashboard (`streamlit run app.py`).
"""

from __future__ import annotations

import os
import socket
from urllib.parse import urlparse

from dotenv import load_dotenv
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

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

# A refund request large enough to require supervisor approval, demonstrating
# Phase 3's human-in-the-loop Approval Gate (use case 7).
REFUND_MESSAGE = "I want a refund for my faulty dishwasher. My order is ORD-1098."


def _enable_mlflow_tracing_if_available(tracking_uri: str, experiment: str, timeout: float = 0.5) -> bool:
    """Enable MLflow autologging only if the tracking server is actually
    reachable. `mlflow.set_experiment()` blocks when the server is
    unreachable, and MLflow is meant to run on-demand (see
    start_mlflow.ps1), not always-on - so this does a quick socket check
    first instead of letting the script hang."""
    parsed = urlparse(tracking_uri)
    host, port = parsed.hostname or "127.0.0.1", parsed.port or 80
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError:
        print(f"[mlflow] Tracking server not reachable at {tracking_uri} - running without tracing.")
        return False

    import mlflow

    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(experiment)
    mlflow.langchain.autolog()
    print(f"[mlflow] Tracing enabled -> {tracking_uri}")
    return True


def print_graph_visualization(graph) -> None:
    """Print the graph's Mermaid diagram source (Phase 4 observability).
    Paste the output into https://mermaid.live or a Markdown ```mermaid
    fenced block to render it."""
    print("\n--- Graph visualization (Mermaid) ---")
    print(graph.get_graph().draw_mermaid())


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


def run_approval_demo(graph) -> None:
    print("\n--- Human-in-the-loop approval demo ---")
    config = {"configurable": {"thread_id": "demo-approval-1"}}

    print(f"\nCustomer: {REFUND_MESSAGE}")
    result = graph.invoke({"customer_message": REFUND_MESSAGE}, config=config)

    if "__interrupt__" in result:
        request = result["__interrupt__"][0].value
        print(f"[Graph paused for CSR approval] {request['prompt']}")
        # In the Streamlit app a human CSR clicks Approve/Deny; here we
        # simulate an approval to show the graph resuming to completion.
        result = graph.invoke(Command(resume="approve"), config=config)

    print(f"CSR reply:\n{result['final_response']}")


if __name__ == "__main__":
    load_dotenv()  # reads OPENAI_API_KEY (and others) from .env

    # InMemorySaver keeps conversation state for the lifetime of this
    # process, keyed by thread_id. Swap in a persistent checkpointer (e.g.
    # SqliteSaver) if state needs to survive a process restart.
    demo_graph = build_graph(checkpointer=InMemorySaver())

    _enable_mlflow_tracing_if_available(
        os.environ.get("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000"), "smarthome_csr"
    )

    print_graph_visualization(demo_graph)
    run_single_turn_demo(demo_graph)
    run_follow_up_demo(demo_graph)
    run_approval_demo(demo_graph)



