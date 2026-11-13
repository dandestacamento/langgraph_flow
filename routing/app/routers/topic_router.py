"""Topic Router: stage 2 of the hybrid routing architecture. Classifies a
question into one or more of the six knowledge-base topics using
structured LLM output plus the topic/subtopic metadata from
`app/config.py`.

The output is always a list (`topics`) rather than a single label so the
same router and the same `RoutingState.selected_topics` field support
Level 1 (always exactly one topic) through Level 7 (multiple topics,
routed in parallel via `app.graph.route_to_agents`) without changing the
schema later.
"""

from __future__ import annotations

import time
from typing import Literal

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.config import ROUTER_MODEL, TOPIC_SUBTOPICS
from app.state import RoutingState

TopicLiteral = Literal[
    "appliances",
    "azure_cloud",
    "data_engineering",
    "python",
    "finance",
    "customer_support",
]

_TOPIC_DESCRIPTIONS = {
    "appliances": "Refrigerators, washing machines, dishwashers: models, features, warranty, fault codes.",
    "azure_cloud": "Azure networking, compute, security, storage: VNets, VMs, RBAC, Blob/Table storage.",
    "data_engineering": "Spark, Databricks, Azure Data Factory: partitions, pipelines, Delta Lake, jobs.",
    "python": "Python fundamentals, OOP, concurrency: functions, decorators, classes, asyncio.",
    "finance": "Personal finance: budgeting, loans/amortization, investment returns and risk.",
    "customer_support": "Customer support policies: orders, refunds, delivery/shipping.",
}


def _topic_router_system_prompt() -> str:
    lines = [
        "You are the Topic Router for a routing accuracy test lab. Classify the user's question "
        "into one or more of these topics (most questions need exactly one):",
        "",
    ]
    for topic, subtopics in TOPIC_SUBTOPICS.items():
        lines.append(f"- {topic}: {_TOPIC_DESCRIPTIONS[topic]} (subtopics: {', '.join(subtopics)})")
    lines.append("")
    lines.append(
        "Watch for overlapping terminology that means different things in different topics - for "
        "example 'partition' refers to a Spark compute partition, an Azure Table Storage partition, "
        "or a physical warehouse storage partition depending on context. Use the surrounding context "
        "of the question, not keyword matching alone, to choose the topic. Business-process anchors "
        "(SmartHome, shipping, warehouses, orders, refunds, customers) are stronger signals than a "
        "generic technical term like 'partition' or 'node' that also appears in cloud/data-engineering "
        "chapters - a question about 'storage partitions in a shipping warehouse' is about "
        "customer_support logistics, not data_engineering or azure_cloud, even though it uses the word "
        "'partition'."
    )
    lines.append(
        "Only include more than one topic if the question genuinely cannot be answered without "
        "evidence from more than one topic area."
    )
    lines.append("")
    lines.append(
        "Also decide: is this question ambiguous? Only set is_ambiguous=true when the question uses "
        "a vague, unresolved reference with NO identifiable subject at all - e.g. 'it'/'this'/'that' "
        "with nothing to anchor what it refers to, or when answering truly depends on a specific "
        "product/model/order/error code that isn't given (e.g. 'how long is the warranty?' - warranty "
        "length genuinely varies by product, so there's no single correct answer without knowing "
        "which one). Do NOT set is_ambiguous=true just because a question is general rather than "
        "product-specific - a question about an overall POLICY (e.g. 'what is the refund policy for "
        "change-of-mind returns?' or 'what format does an order number use?') has one real answer "
        "regardless of product, so it is NOT ambiguous. Still pick your best-guess topics even when "
        "ambiguous."
    )
    return "\n".join(lines)


TOPIC_ROUTER_SYSTEM_PROMPT = _topic_router_system_prompt()


class TopicOutput(BaseModel):
    """Structured output the LLM must produce."""

    is_ambiguous: bool = Field(
        description="True only if the question has no identifiable subject or needs a specific "
        "product/model/order/error code that isn't given - not just because it's a general question."
    )
    topics: list[TopicLiteral] = Field(
        description="Best-guess topic(s) needed to answer the question, most specific/relevant first, "
        "even if is_ambiguous is true."
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in this classification, 0-1.")
    reasoning: str = Field(description="One sentence explaining the classification and ambiguity decision.")


def build_topic_llm() -> ChatOpenAI:
    return ChatOpenAI(model=ROUTER_MODEL, temperature=0).with_structured_output(TopicOutput)


def classify_topic(state: RoutingState) -> dict:
    """Router node: classify the question into one or more topics, and
    flag whether it's too ambiguous to route confidently."""
    start = time.perf_counter()
    llm = build_topic_llm()
    result: TopicOutput = llm.invoke(
        [
            ("system", TOPIC_ROUTER_SYSTEM_PROMPT),
            ("human", state["question"]),
        ]
    )
    duration_ms = (time.perf_counter() - start) * 1000

    topics = list(dict.fromkeys(result.topics)) or ["customer_support"]
    decision: dict = {
        "topics": topics,
        "is_ambiguous": result.is_ambiguous,
        "confidence": result.confidence,
        "reasoning": result.reasoning,
    }

    return {
        "topic_decision": decision,
        "selected_topics": topics,
        "execution_log": [
            {
                "node": "topic_router",
                "action": "classify_topic",
                "output": decision,
                "duration_ms": round(duration_ms, 1),
            }
        ],
    }
