"""Shared helper for the six topic agents (appliance, azure, data
engineering, python, finance, customer_support).

Level 1 agents answer directly from the LLM's own knowledge plus a
topic-scoped system prompt - they do not yet retrieve from the knowledge
base (that's Level 4, via `app/rag`). Factoring the actual LLM call out
into one function here keeps each per-topic agent file to "what topic am
I, and what's my prompt", which is what later levels (RAG context
injection, tool calls) will need to extend independently per topic.
"""

from __future__ import annotations

import time

from langchain_openai import ChatOpenAI

from app.config import AGENT_MODEL, TOPIC_SUBTOPICS
from app.state import RoutingState

_AGENT_SYSTEM_PROMPTS = {
    "appliances": (
        "You are the Appliances Agent for SmartHome Appliances, answering questions about "
        "refrigerators, washing machines, and dishwashers: models, features, warranty terms, and "
        "fault/error codes. Be precise about model numbers - warranty and capacity differ by model."
    ),
    "azure_cloud": (
        "You are the Azure Cloud Agent, answering questions about Azure networking, compute, "
        "security, and storage: VNets, subnets, NSGs, VMs, RBAC, managed identity, Key Vault, and "
        "Blob/Table storage."
    ),
    "data_engineering": (
        "You are the Data Engineering Agent, answering questions about Apache Spark, Databricks, "
        "and Azure Data Factory: partitions, shuffles, Delta Lake, jobs, pipelines, and triggers."
    ),
    "python": (
        "You are the Python Agent, answering questions about Python fundamentals, OOP, and "
        "concurrency: functions, decorators, classes, inheritance, threading, and asyncio."
    ),
    "finance": (
        "You are the Finance Agent, answering general personal-finance questions about budgeting, "
        "loans/amortization, and investment returns and risk. Do not give individualized financial "
        "advice - explain general concepts only."
    ),
    "customer_support": (
        "You are the Customer Support Agent for SmartHome Appliances, answering questions about "
        "order placement/tracking/cancellation, refund policy, and delivery/shipping."
    ),
}


def run_topic_agent(topic: str, state: RoutingState) -> dict:
    """Shared node body for every topic agent: answer the question using a
    topic-scoped system prompt, and record the result under
    `agent_responses[topic]`."""
    start = time.perf_counter()
    llm = ChatOpenAI(model=AGENT_MODEL, temperature=0)
    system_prompt = _AGENT_SYSTEM_PROMPTS[topic] + (
        f" Relevant subtopics: {', '.join(TOPIC_SUBTOPICS[topic])}. "
        "If the question is outside your topic, say so briefly instead of guessing."
    )
    response = llm.invoke(
        [
            ("system", system_prompt),
            ("human", state["question"]),
        ]
    )
    duration_ms = (time.perf_counter() - start) * 1000
    answer = response.content

    return {
        "agent_responses": {topic: answer},
        "execution_log": [
            {
                "node": f"{topic}_agent",
                "action": "answer",
                "output": {"answer_preview": answer[:200]},
                "duration_ms": round(duration_ms, 1),
            }
        ],
    }
