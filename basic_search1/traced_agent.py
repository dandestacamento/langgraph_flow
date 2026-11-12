"""A slightly more realistic "agent" to demonstrate tracing/observability.

Unlike app.py (a fixed 2-node pipeline), this agent makes a *decision* about
which tool to call based on the input, then calls that tool. This is the same
shape as a real LLM agent (router -> tool call -> final answer), just using
simple rule-based logic instead of an LLM so it runs with zero API keys/cost.

Tracing setup:
  - mlflow.langchain.autolog() auto-captures the whole graph run (every node,
    every edge taken) as a trace, with no extra code per node.
  - Inside the tool nodes we additionally open manual child spans with
    mlflow.start_span(...) to show how you can log extra detail (e.g. which
    branch was picked, raw tool inputs/outputs) beyond what autolog captures.

Run it, then open http://127.0.0.1:5000 (or wherever your MLflow server is)
and look at the "agent_traces" experiment's Traces tab to see:
  - The decision the router made ("route" output)
  - Which tool node actually ran
  - The manual spans with their own inputs/outputs/timing
"""

import os
import re
import time
from typing import TypedDict

import mlflow
from langgraph.graph import StateGraph, START, END
from mlflow.entities import SpanType


class AgentState(TypedDict):
    query: str
    route: str
    result: str


def router(state: AgentState) -> AgentState:
    """Decide which tool to use based on keywords in the query (stand-in for
    an LLM making a tool-choice decision)."""
    query = state["query"].lower()
    if any(ch.isdigit() for ch in query) or "+" in query or "calculate" in query:
        route = "calculator"
    else:
        route = "search"
    return {"route": route}


def pick_route(state: AgentState) -> str:
    """Conditional edge function: tells LangGraph which node to go to next."""
    return state["route"]


def calculator_tool(state: AgentState) -> AgentState:
    with mlflow.start_span(name="calculator_tool", span_type=SpanType.TOOL) as span:
        span.set_inputs({"query": state["query"]})
        time.sleep(0.1)  # simulate work
        # Extremely naive "calculator": sum any numbers found in the query.
        numbers = [int(tok) for tok in re.findall(r"\d+", state["query"])]
        total = sum(numbers) if numbers else 0
        output = f"The total is {total}"
        span.set_outputs({"result": output})
    return {"result": output}


def search_tool(state: AgentState) -> AgentState:
    with mlflow.start_span(name="search_tool", span_type=SpanType.TOOL) as span:
        span.set_inputs({"query": state["query"]})
        time.sleep(0.1)  # simulate work
        output = f"Here is what I found about '{state['query']}'"
        span.set_outputs({"result": output})
    return {"result": output}


def respond(state: AgentState) -> AgentState:
    return {"result": f"[via {state['route']}] {state['result']}"}


def build_agent():
    graph = StateGraph(AgentState)
    graph.add_node("router", router)
    graph.add_node("calculator", calculator_tool)
    graph.add_node("search", search_tool)
    graph.add_node("respond", respond)

    graph.add_edge(START, "router")
    graph.add_conditional_edges(
        "router",
        pick_route,
        {"calculator": "calculator", "search": "search"},
    )
    graph.add_edge("calculator", "respond")
    graph.add_edge("search", "respond")
    graph.add_edge("respond", END)

    return graph.compile()


if __name__ == "__main__":
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000"))
    mlflow.set_experiment("agent_traces")
    mlflow.langchain.autolog()

    agent = build_agent()

    for query in ["What is 4 + 5 + 10?", "Tell me about the Eiffel Tower"]:
        result = agent.invoke({"query": query, "route": "", "result": ""})
        print(f"{query!r} -> {result['result']!r}")
