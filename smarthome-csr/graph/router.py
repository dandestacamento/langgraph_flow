"""Intent Router: classifies a customer message into one or more specialist
agents using structured LLM output.

A single message can require more than one agent (e.g. a fault on a product
that is still under warranty needs both `technical` and `warranty`), so the
router always returns a list of intents rather than a single label.
"""

from __future__ import annotations

import time
from typing import Literal

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from graph.state import CSRState

ROUTER_SYSTEM_PROMPT = """You are the Intent Router for SmartHome Appliances, an Australian \
retailer selling refrigerators, washing machines, dryers, dishwashers, ovens and air conditioners.

Classify the customer's message into one or more of these specialist agents:
- product: product availability, specs, comparisons, recommendations, pricing
- technical: fault diagnosis / troubleshooting for an appliance the customer owns
- warranty: warranty coverage, eligibility, replacement under warranty
- orders: order status, delivery tracking
- returns: refunds, returns, faulty-item replacement requests

Only include an agent if it is genuinely required to resolve the message."""


class RouterOutput(BaseModel):
    """Structured output the LLM must produce."""

    intents: list[Literal["product", "technical", "warranty", "orders", "returns"]] = Field(
        description="One or more specialist agents needed to resolve the customer's message."
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in this classification, 0-1.")
    reasoning: str = Field(description="One sentence explaining the classification.")


def build_router_llm() -> ChatOpenAI:
    return ChatOpenAI(model="gpt-4o-mini", temperature=0).with_structured_output(RouterOutput)


def classify_intent(state: CSRState) -> dict:
    """Router node: classify the customer's message and record selected agents."""
    start = time.perf_counter()
    llm = build_router_llm()
    result: RouterOutput = llm.invoke(
        [
            ("system", ROUTER_SYSTEM_PROMPT),
            ("human", state["customer_message"]),
        ]
    )
    duration_ms = (time.perf_counter() - start) * 1000

    decision: dict = {
        "intents": result.intents,
        "confidence": result.confidence,
        "reasoning": result.reasoning,
    }

    return {
        "router_decision": decision,
        "selected_agents": result.intents,
        "execution_log": [
            {
                "node": "router",
                "action": "classify_intent",
                "output": decision,
                "duration_ms": round(duration_ms, 1),
            }
        ],
    }
