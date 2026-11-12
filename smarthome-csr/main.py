"""Application entry point for the SmartHome Appliances CSR Assistant.

Run this directly for a quick command-line smoke test of the LangGraph
workflow before launching the Streamlit dashboard (`streamlit run app.py`).
"""

from __future__ import annotations

import os

import mlflow
from dotenv import load_dotenv

from graph.workflow import build_graph

SAMPLE_MESSAGES = [
    "Do you have a Bosch Series 6 dishwasher in stock?",
    "My washing machine makes a loud banging noise during spinning.",
    "Is my refrigerator still under warranty? Order ORD-1045.",
]


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


def run_demo() -> None:
    graph = build_graph()
    for message in SAMPLE_MESSAGES:
        result = graph.invoke(new_state(message))
        print(f"\nCustomer: {message}")
        print(f"Router -> {result['router_decision']}")
        print(f"CSR reply:\n{result['final_response']}")


if __name__ == "__main__":
    load_dotenv()  # reads OPENAI_API_KEY (and others) from .env

    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000"))
    mlflow.set_experiment("smarthome_csr")
    mlflow.langchain.autolog()

    run_demo()
