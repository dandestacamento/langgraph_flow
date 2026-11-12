"""Complexity Router: stage 1 of the hybrid routing architecture described
in instructions/Langgraph_routing/6_routing_design.md. Classifies a
question as simple / intermediate / complex before any topic routing
happens, so the graph can later branch between a direct single-agent path
(simple), a RAG-backed path (intermediate), and a multi-agent planning
path (complex).

Level 1 test questions are always "simple" by construction, and the graph
currently routes every complexity the same way (straight to the topic
router) - the branch point this decision will drive is added when later
levels (5, 7, 9) need different handling per complexity tier. Recording
the decision now means we don't have to re-run anything when that branch
is added.
"""

from __future__ import annotations

import time
from typing import Literal

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.config import ROUTER_MODEL
from app.state import RoutingState

COMPLEXITY_SYSTEM_PROMPT = """You are the Complexity Router for a routing accuracy test lab that \
answers questions about appliances, Azure Cloud, data engineering, Python, finance, and customer \
support.

Classify the user's question into exactly one complexity tier:
- simple: a single, self-contained fact or concept lookup, answerable from one topic area.
- intermediate: needs supporting evidence from documents/passages, or spans one topic but
  multiple chapters/subtopics.
- complex: needs multiple topics, multi-step reasoning, or combining facts that aren't stated
  together anywhere in the source material.

Be decisive - most everyday questions are "simple"."""


class ComplexityOutput(BaseModel):
    """Structured output the LLM must produce."""

    complexity: Literal["simple", "intermediate", "complex"] = Field(
        description="The complexity tier for this question."
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in this classification, 0-1.")
    reasoning: str = Field(description="One sentence explaining the classification.")


def build_complexity_llm() -> ChatOpenAI:
    return ChatOpenAI(model=ROUTER_MODEL, temperature=0).with_structured_output(ComplexityOutput)


def classify_complexity(state: RoutingState) -> dict:
    """Router node: classify the question's complexity tier."""
    start = time.perf_counter()
    llm = build_complexity_llm()
    result: ComplexityOutput = llm.invoke(
        [
            ("system", COMPLEXITY_SYSTEM_PROMPT),
            ("human", state["question"]),
        ]
    )
    duration_ms = (time.perf_counter() - start) * 1000

    decision: dict = {
        "complexity": result.complexity,
        "confidence": result.confidence,
        "reasoning": result.reasoning,
    }

    return {
        "complexity_decision": decision,
        "execution_log": [
            {
                "node": "complexity_router",
                "action": "classify_complexity",
                "output": decision,
                "duration_ms": round(duration_ms, 1),
            }
        ],
    }
