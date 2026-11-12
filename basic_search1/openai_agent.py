"""A real LLM-driven agent (OpenAI + LangGraph), traced with MLflow.

Unlike traced_agent.py (keyword-based rule router), this agent uses an actual
LLM (gpt-4o-mini) with tool-calling: the model itself decides, per query,
whether to call `calculator`, `search`, both, or neither, and produces the
final natural-language answer.

Standard LangGraph "ReAct" loop:
  agent (LLM w/ tools bound) -> tools_condition -> tools (ToolNode) -> agent -> ...
  until the LLM responds without requesting another tool call -> END

Tracing: mlflow.langchain.autolog() captures every LLM call (prompt,
response, tool-call requests, token usage/cost) and every tool execution
automatically, with no manual spans needed since ChatOpenAI and the tools
below are native LangChain Runnables.

Requires OPENAI_API_KEY to be set (loaded here from a .env file via
python-dotenv). The search tool is intentionally mocked - no external search
API is called.
"""

import os
import re
import time

import mlflow
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition


@tool
def calculator(expression: str) -> str:
    """Evaluate a simple arithmetic expression by summing the numbers in it,
    e.g. '4 + 5 + 10' -> 19. Use this for any math question."""
    numbers = [int(n) for n in re.findall(r"-?\d+", expression)]
    return f"The total is {sum(numbers)}"


@tool
def search(query: str) -> str:
    """Search the web for information about a topic. (Mocked for this demo:
    returns a canned response instead of calling a real search API.)"""
    time.sleep(0.1)  # simulate network latency
    return f"Here is what I found about '{query}': [mocked search result]"


TOOLS = [calculator, search]


def build_agent():
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0).bind_tools(TOOLS)

    def call_model(state: MessagesState):
        response = llm.invoke(state["messages"])
        return {"messages": [response]}

    graph = StateGraph(MessagesState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", ToolNode(TOOLS))

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")

    return graph.compile()


if __name__ == "__main__":
    load_dotenv()  # reads OPENAI_API_KEY (and others) from .env

    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000"))
    mlflow.set_experiment("openai_agent_traces")
    mlflow.langchain.autolog()

    agent = build_agent()

    for query in ["What is 4 + 5 + 10?", "Tell me about the Eiffel Tower"]:
        result = agent.invoke({"messages": [("user", query)]})
        print(f"{query!r} -> {result['messages'][-1].content!r}")
