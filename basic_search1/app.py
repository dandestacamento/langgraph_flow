"""A very simple LangGraph app.

Builds a tiny graph with two nodes:
1. greet       - adds a greeting to the state
2. shout       - uppercases the message

Run it directly to see the graph execute end-to-end.
"""

import os
from typing import TypedDict

import mlflow
from langgraph.graph import StateGraph, START, END


class State(TypedDict):
    name: str
    message: str


def greet(state: State) -> State:
    return {"message": f"Hello, {state['name']}!"}


def shout(state: State) -> State:
    return {"message": state["message"].upper()}


def build_graph():
    graph = StateGraph(State)
    graph.add_node("greet", greet)
    graph.add_node("shout", shout)

    graph.add_edge(START, "greet")
    graph.add_edge("greet", "shout")
    graph.add_edge("shout", END)

    return graph.compile()


if __name__ == "__main__":
    # MLflow tracing: point at a local server (started with `mlflow server`)
    # and auto-instrument every LangGraph/LangChain run.
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000"))
    mlflow.set_experiment("langgraph_flow")
    mlflow.langchain.autolog()

    app = build_graph()
    result = app.invoke({"name": "world", "message": ""})
    print(result["message"])
